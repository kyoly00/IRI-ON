"""Silero VAD v5 ONNX 기반 고신뢰 음성 검출기.

주방의 물소리, 식기 부딪힘, 환풍기 소음 등 고에너지 비음성 노이즈를 걸러내고,
순수 인간 음성 확률(P(speech) > 0.5)을 기반으로 정확한 발화 시작과 종료를 판정한다.
ONNX runtime 미설치 또는 모델 부재 시 기존 AdaptiveEnergyEndpointDetector로 안전하게 fallback한다.
"""

from __future__ import annotations

from collections import deque
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

from .audio import AdaptiveEnergyEndpointDetector, AudioEvent
from .config import CustomVoiceSettings

logger = logging.getLogger("uvicorn.error")

_DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "silero_vad.onnx"


class SileroVADDetector:
    """Silero VAD v5 ONNX 모델을 사용한 프레임 단위 음성 판정기."""

    def __init__(
        self,
        settings: CustomVoiceSettings,
        model_path: Optional[Path | str] = None,
        threshold: float = 0.5,
    ) -> None:
        import onnxruntime as ort

        path = Path(model_path or getattr(settings, "vad_model_path", None) or _DEFAULT_MODEL_PATH)
        if not path.exists():
            raise FileNotFoundError(f"Silero VAD model not found at {path}")

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.session = ort.InferenceSession(str(path), sess_options=opts)
        self.settings = settings
        self.model_path = str(path)
        self.threshold = threshold
        self.sample_rate = settings.input_sample_rate  # 16000
        self._sr_tensor = np.array(self.sample_rate, dtype=np.int64)

        # Silero VAD 16kHz는 512 샘플(32ms = 1024 bytes) 단위로 추론한다.
        self.frame_samples = 512
        self.frame_bytes = self.frame_samples * 2  # 1024 bytes
        self.frame_ms = (self.frame_samples / self.sample_rate) * 1000.0  # 32.0 ms

        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        # Silero ONNX wrapper는 각 512-sample frame 앞에 이전 64 sample을 붙인다.
        # ONNX input shape가 dynamic이라 context 없이도 실행되지만, 공식 streaming
        # 경로와 달라져 확률이 지나치게 낮아질 수 있다.
        self._context = np.zeros((1, 64), dtype=np.float32)
        self._pending = bytearray()
        self._pre_roll: deque[bytes] = deque(maxlen=8)
        self._speech = bytearray()

        self._speech_start_frames = max(2, getattr(settings, "speech_start_frames", 3))
        self._voiced_run = 0
        self._silence_run = 0
        self._talking = False
        self.last_probability: float | None = None
        self.last_voiced = False
        self.speech_duration_ms = 0.0
        self.silence_duration_ms = 0.0
        self._diagnostic_frames = 0
        self._diagnostic_above_threshold = 0
        self._diagnostic_max_probability = 0.0
        self._diagnostic_longest_voiced_run = 0
        self._frame_index = 0

    @property
    def talking(self) -> bool:
        """현재 사용자가 발화 중인지 여부."""
        return self._talking

    @property
    def current_utterance(self) -> bytes:
        """Speech-start 이전 pre-roll을 포함한 현재 발화 snapshot."""
        return bytes(self._speech)

    def reset(self) -> None:
        """세션 유지 상태에서 내부 버퍼 및 RNN 히든 state를 리셋한다."""
        self._pending.clear()
        self._pre_roll.clear()
        self._speech.clear()
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)
        self._voiced_run = 0
        self._silence_run = 0
        self._talking = False
        self.last_probability = None
        self.last_voiced = False
        self.speech_duration_ms = 0.0
        self.silence_duration_ms = 0.0
        self._diagnostic_frames = 0
        self._diagnostic_above_threshold = 0
        self._diagnostic_max_probability = 0.0
        self._diagnostic_longest_voiced_run = 0
        self._frame_index = 0

    def drain_diagnostics(self) -> dict[str, float | int]:
        """최근 logging window의 모델 확률 분포를 반환하고 다음 window를 시작한다."""

        result = {
            "frames": self._diagnostic_frames,
            "max_probability": self._diagnostic_max_probability,
            "above_threshold": self._diagnostic_above_threshold,
            "longest_voiced_run": self._diagnostic_longest_voiced_run,
            "start_threshold": self.threshold,
            "required_start_frames": self._speech_start_frames,
        }
        self._diagnostic_frames = 0
        self._diagnostic_above_threshold = 0
        self._diagnostic_max_probability = 0.0
        self._diagnostic_longest_voiced_run = 0
        return result

    def push(self, pcm: bytes) -> list[AudioEvent]:
        """임의 길이의 16kHz 16-bit mono PCM을 512샘플 단위로 나누어 Silero VAD 추론."""
        self._pending.extend(pcm)
        events: list[AudioEvent] = []
        while len(self._pending) >= self.frame_bytes:
            frame = bytes(self._pending[: self.frame_bytes])
            del self._pending[: self.frame_bytes]
            event = self._process_frame(frame)
            if event is not None:
                events.append(event)
        return events

    def _process_frame(self, frame: bytes) -> Optional[AudioEvent]:
        # [-1.0, 1.0] 범위로 정규화
        samples = np.frombuffer(frame, dtype="<i2").astype(np.float32) / 32768.0
        audio_tensor = samples.reshape(1, self.frame_samples)
        model_input = np.concatenate((self._context, audio_tensor), axis=1)
        input_rms = float(np.sqrt(np.mean(samples * samples)))
        input_peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        context_rms = float(np.sqrt(np.mean(self._context * self._context)))

        try:
            out, new_state = self.session.run(
                None,
                {"input": model_input, "state": self._state, "sr": self._sr_tensor},
            )
            self._state = new_state
            self._context = model_input[:, -64:].copy()
            speech_prob = float(out[0][0])
            self.last_probability = speech_prob
        except Exception as exc:
            logger.warning("[SileroVAD] Inference failed: %s", exc)
            return None

        voiced = speech_prob >= self.threshold
        self.last_voiced = voiced
        self._frame_index += 1
        self._diagnostic_frames += 1
        self._diagnostic_max_probability = max(self._diagnostic_max_probability, speech_prob)
        if voiced:
            self._diagnostic_above_threshold += 1

        if not self._talking:
            self._pre_roll.append(frame)
            self._voiced_run = self._voiced_run + 1 if voiced else 0
            self._diagnostic_longest_voiced_run = max(
                self._diagnostic_longest_voiced_run,
                self._voiced_run,
            )
            if (
                self.settings.vad_debug_logging
                or speech_prob >= 0.05
                or input_rms >= 0.06
            ):
                logger.info(
                    "[SileroVAD] frame=%s input_samples=%s context_samples=%s rms=%.4f peak=%.4f "
                    "context_rms=%.4f prob=%.4f threshold=%.2f voiced=%s run=%s/%s state_l2=%.3f",
                    self._frame_index,
                    self.frame_samples,
                    model_input.shape[1] - self.frame_samples,
                    input_rms,
                    input_peak,
                    context_rms,
                    speech_prob,
                    self.threshold,
                    voiced,
                    self._voiced_run,
                    self._speech_start_frames,
                    float(np.linalg.norm(self._state)),
                )
            if self._voiced_run >= self._speech_start_frames:
                self._talking = True
                self._speech.extend(b"".join(self._pre_roll))
                self._pre_roll.clear()
                self._silence_run = 0
                self.speech_duration_ms = len(self._pre_roll) * self.frame_ms
                self.silence_duration_ms = 0.0
                logger.info("[SileroVAD] speech started (prob=%.3f >= %.2f)", speech_prob, self.threshold)
                return AudioEvent(kind="speech_start", utterance=bytes(self._speech))
            return None

        self._speech.extend(frame)
        if (
            self.settings.vad_debug_logging
            or speech_prob >= 0.05
            or input_rms >= 0.06
        ):
            logger.info(
                "[SileroVAD] frame=%s talking=true rms=%.4f peak=%.4f context_rms=%.4f "
                "prob=%.4f threshold=%.2f silence_run=%s state_l2=%.3f",
                self._frame_index,
                input_rms,
                input_peak,
                context_rms,
                speech_prob,
                self.threshold,
                self._silence_run,
                float(np.linalg.norm(self._state)),
            )
        # 히스테리시스: 발화 종료 침묵 판정은 기준보다 약간 낮은 임계치 사용
        is_silent = speech_prob < (self.threshold - 0.15)
        self._silence_run = self._silence_run + 1 if is_silent else 0

        speech_ms = len(self._speech) / 2 / self.sample_rate * 1000.0
        silence_ms = self._silence_run * self.frame_ms
        self.speech_duration_ms = speech_ms
        self.silence_duration_ms = silence_ms

        reached_maximum = speech_ms >= self.settings.maximum_speech_ms
        reached_endpoint = (
            speech_ms >= self.settings.minimum_speech_ms
            and silence_ms >= self.settings.endpoint_hard_silence_ms
        )

        if reached_endpoint or reached_maximum:
            utterance = bytes(self._speech)
            duration_ms = speech_ms
            self._speech.clear()
            self._voiced_run = 0
            self._silence_run = 0
            self._talking = False
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            logger.info(
                "[SileroVAD] speech ended (duration_ms=%.1f, silence_ms=%.1f, max=%s)",
                duration_ms,
                silence_ms,
                reached_maximum,
            )
            return AudioEvent(kind="turn_end", utterance=utterance, duration_ms=duration_ms)

        return None


def create_vad_detector(settings: CustomVoiceSettings):
    """설정에 따라 Silero VAD를 생성하고, 실패 시 AdaptiveEnergyEndpointDetector로 fallback한다."""
    vad_mode = getattr(settings, "vad_backend", getattr(settings, "vad_mode", "silero"))
    if vad_mode == "energy":
        return AdaptiveEnergyEndpointDetector(settings)

    if vad_mode == "marblenet":
        try:
            from .nemo_vad import MarbleNetVADDetector

            return MarbleNetVADDetector(settings)
        except Exception as exc:
            logger.warning(
                "[CustomVoice] Failed to initialize MarbleNetVADDetector (%s). "
                "Falling back to SileroVADDetector.",
                exc,
            )

    try:
        threshold = getattr(settings, "vad_threshold", 0.5)
        return SileroVADDetector(settings, threshold=threshold)
    except Exception as exc:
        logger.warning(
            "[CustomVoice] Failed to initialize SileroVADDetector (%s). Falling back to AdaptiveEnergyEndpointDetector.",
            exc,
        )
        return AdaptiveEnergyEndpointDetector(settings)
