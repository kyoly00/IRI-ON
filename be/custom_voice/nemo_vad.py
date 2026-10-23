"""NVIDIA Frame-VAD Multilingual MarbleNet v2.0 streaming-context adapter."""

from __future__ import annotations

from collections import deque
import logging
from typing import Optional

import numpy as np

from .audio import AudioEvent
from .config import CustomVoiceSettings


logger = logging.getLogger("uvicorn.error")


class MarbleNetVADDetector:
    """20 ms frame score를 rolling acoustic context와 후처리 상태에 연결한다."""

    def __init__(self, settings: CustomVoiceSettings) -> None:
        import torch
        import nemo.collections.asr as nemo_asr

        self.settings = settings
        self.sample_rate = settings.input_sample_rate
        if self.sample_rate != 16_000:
            raise ValueError("MarbleNet VAD requires 16 kHz mono PCM")
        self.frame_samples = self.sample_rate * 20 // 1000
        self.frame_bytes = self.frame_samples * 2
        self._torch = torch
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = nemo_asr.models.EncDecFrameClassificationModel.from_pretrained(
            model_name=settings.marblenet_model
        ).to(self.device)
        self.model.eval()

        self._pending = bytearray()
        self._unscored: deque[bytes] = deque()
        context_frames = max(10, settings.marblenet_context_ms // 20)
        self._context: deque[bytes] = deque(maxlen=context_frames)
        self._inference_frames = max(1, settings.marblenet_inference_interval_ms // 20)
        self._pre_roll: deque[bytes] = deque(maxlen=max(8, context_frames // 4))
        self._speech = bytearray()
        self._voiced_run = 0
        self._silence_run = 0
        self._talking = False
        self.last_probability: float | None = None
        self.last_voiced = False
        self.speech_duration_ms = 0.0
        self.silence_duration_ms = 0.0

    @property
    def talking(self) -> bool:
        return self._talking

    @property
    def current_utterance(self) -> bytes:
        """Speech-start 이전 pre-roll을 포함한 현재 발화 snapshot."""
        return bytes(self._speech)

    def reset(self) -> None:
        self._pending.clear()
        self._unscored.clear()
        self._context.clear()
        self._pre_roll.clear()
        self._speech.clear()
        self._voiced_run = 0
        self._silence_run = 0
        self._talking = False
        self.last_probability = None
        self.last_voiced = False
        self.speech_duration_ms = 0.0
        self.silence_duration_ms = 0.0

    def push(self, pcm: bytes) -> list[AudioEvent]:
        self._pending.extend(pcm)
        events: list[AudioEvent] = []
        while len(self._pending) >= self.frame_bytes:
            frame = bytes(self._pending[: self.frame_bytes])
            del self._pending[: self.frame_bytes]
            self._context.append(frame)
            self._unscored.append(frame)
            if len(self._unscored) < self._inference_frames:
                continue
            probabilities = self._infer_context(len(self._unscored))
            for probability in probabilities:
                scored_frame = self._unscored.popleft()
                event = self._process_scored_frame(scored_frame, probability)
                if event is not None:
                    events.append(event)
        return events

    def _infer_context(self, needed: int) -> list[float]:
        signal = np.frombuffer(b"".join(self._context), dtype="<i2").astype(np.float32) / 32768.0
        tensor = self._torch.from_numpy(signal).unsqueeze(0).to(self.device)
        length = self._torch.tensor([tensor.shape[1]], dtype=self._torch.long, device=self.device)
        with self._torch.no_grad():
            output = self.model(input_signal=tensor, input_signal_length=length)
            if isinstance(output, (tuple, list)):
                output = output[0]
            if output.shape[-1] >= 2:
                probabilities = self._torch.softmax(output, dim=-1)[0, :, 1]
            else:
                probabilities = self._torch.sigmoid(output.reshape(-1))
        values = probabilities.detach().float().cpu().numpy().reshape(-1)
        if values.size < needed:
            raise RuntimeError(
                f"MarbleNet returned {values.size} frame scores for {needed} pending frames"
            )
        return [float(value) for value in values[-needed:]]

    def _process_scored_frame(self, frame: bytes, speech_probability: float) -> Optional[AudioEvent]:
        self.last_probability = speech_probability
        voiced = speech_probability >= self.settings.vad_threshold
        self.last_voiced = voiced
        if not self._talking:
            self._pre_roll.append(frame)
            self._voiced_run = self._voiced_run + 1 if voiced else 0
            if self._voiced_run >= self.settings.speech_start_frames:
                self._talking = True
                self._speech.extend(b"".join(self._pre_roll))
                self._pre_roll.clear()
                self._silence_run = 0
                self.speech_duration_ms = 0.0
                self.silence_duration_ms = 0.0
                logger.info(
                    "[MarbleNetVAD] speech started (prob=%.3f threshold=%.2f)",
                    speech_probability,
                    self.settings.vad_threshold,
                )
                return AudioEvent(kind="speech_start", utterance=bytes(self._speech))
            return None

        self._speech.extend(frame)
        # 시작 threshold보다 낮은 종료 threshold를 두어 단어 사이 확률 흔들림을 흡수한다.
        silent = speech_probability < max(0.05, self.settings.vad_threshold - 0.15)
        self._silence_run = self._silence_run + 1 if silent else 0
        speech_ms = len(self._speech) / 2 / self.sample_rate * 1000.0
        silence_ms = self._silence_run * 20.0
        self.speech_duration_ms = speech_ms
        self.silence_duration_ms = silence_ms
        reached_end = (
            speech_ms >= self.settings.minimum_speech_ms
            and silence_ms >= self.settings.endpoint_hard_silence_ms
        )
        reached_max = speech_ms >= self.settings.maximum_speech_ms
        if not (reached_end or reached_max):
            return None

        utterance = bytes(self._speech)
        self._speech.clear()
        self._voiced_run = 0
        self._silence_run = 0
        self._talking = False
        return AudioEvent(kind="turn_end", utterance=utterance, duration_ms=speech_ms)
