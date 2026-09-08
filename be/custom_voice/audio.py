"""브라우저 PCM 입력의 framing, VAD/endpointing, prosody 추출.

LiveKit이나 별도 VAD SDK 없이도 동작하도록 signed 16-bit PCM과 NumPy 연산만
사용한다. 전송·발화 검출·특징 추출의 책임을 각각 작은 클래스로 나눴다.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Literal, Optional

import numpy as np

from .config import CustomVoiceSettings


@dataclass(frozen=True)
class AudioEvent:
    """오디오 프레임 처리 결과. ``utterance``는 turn_end일 때만 채워진다."""

    kind: Literal["speech_start", "turn_end"]
    utterance: Optional[bytes] = None
    duration_ms: float = 0.0


class AdaptiveEnergyEndpointDetector:
    """주변 소음에 적응하는 energy VAD와 발화 종료 정책을 직접 구현한다."""

    def __init__(self, settings: CustomVoiceSettings) -> None:
        self.settings = settings
        self.frame_samples = settings.input_sample_rate * settings.input_frame_ms // 1000
        self.frame_bytes = self.frame_samples * 2
        self._pending = bytearray()
        self._pre_roll: deque[bytes] = deque(maxlen=8)
        self._speech = bytearray()
        self._noise_rms = settings.vad_min_rms / settings.vad_noise_multiplier
        self._voiced_run = 0
        self._silence_run = 0
        self._talking = False

    @property
    def talking(self) -> bool:
        """현재 detector가 사용자 발화 안에 있는지 반환한다."""

        return self._talking

    def reset(self) -> None:
        """연결은 유지한 채 현재 발화 관련 버퍼만 비운다."""

        self._pending.clear()
        self._pre_roll.clear()
        self._speech.clear()
        self._voiced_run = 0
        self._silence_run = 0
        self._talking = False

    def push(self, pcm: bytes) -> list[AudioEvent]:
        """길이가 임의인 PCM 조각을 30 ms 프레임으로 정렬해 처리한다."""

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
        """한 PCM 프레임을 분류하고 상태 전이에 해당하는 이벤트만 반환한다."""

        samples = np.frombuffer(frame, dtype="<i2").astype(np.float32)
        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0

        # 말하지 않는 구간만 noise floor를 천천히 갱신해 사람 목소리에 끌려가지 않게 한다.
        if not self._talking and rms < max(self.settings.vad_min_rms * 2.0, self._noise_rms * 4.0):
            self._noise_rms = 0.96 * self._noise_rms + 0.04 * rms
        threshold = max(self.settings.vad_min_rms, self._noise_rms * self.settings.vad_noise_multiplier)
        voiced = rms >= threshold

        if not self._talking:
            self._pre_roll.append(frame)
            self._voiced_run = self._voiced_run + 1 if voiced else 0
            if self._voiced_run >= self.settings.speech_start_frames:
                self._talking = True
                self._speech.extend(b"".join(self._pre_roll))
                self._pre_roll.clear()
                self._silence_run = 0
                return AudioEvent(kind="speech_start")
            return None

        self._speech.extend(frame)
        self._silence_run = 0 if voiced else self._silence_run + 1
        speech_ms = len(self._speech) / 2 / self.settings.input_sample_rate * 1000.0
        silence_ms = self._silence_run * self.settings.input_frame_ms

        # 너무 긴 독백은 메모리 보호를 위해 강제로 닫고, 정상 발화는 지정 침묵에서 닫는다.
        reached_maximum = speech_ms >= self.settings.maximum_speech_ms
        reached_endpoint = (
            speech_ms >= self.settings.minimum_speech_ms
            and silence_ms >= self.settings.endpoint_silence_ms
        )
        if reached_endpoint or reached_maximum:
            utterance = bytes(self._speech)
            duration_ms = speech_ms
            self._speech.clear()
            self._voiced_run = 0
            self._silence_run = 0
            self._talking = False
            return AudioEvent(kind="turn_end", utterance=utterance, duration_ms=duration_ms)
        return None


@dataclass(frozen=True)
class ProsodyMetadata:
    """LLM에 전달하기 전에 낮은 cardinality로 정규화한 운율 정보."""

    pitch_mean_hz: Optional[float]
    rms_energy: float
    speech_rate_hint: Literal["slow", "normal", "fast"]
    emotion_hint: Literal["calm", "neutral", "urgent"]
    urgency: float

    def prompt_hint(self) -> str:
        """수치 전체 대신 응답 스타일에 필요한 최소 힌트만 만든다."""

        return (
            f"[voice_context emotion={self.emotion_hint}, "
            f"pace={self.speech_rate_hint}, urgency={self.urgency:.2f}]"
        )


class ProsodyExtractor:
    """원본 PCM에서 energy, pitch, tempo 힌트를 계산하는 가벼운 sidecar."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate

    def extract(self, pcm: bytes) -> ProsodyMetadata:
        """오디오 전체의 통계로 안정적인 turn-level prosody를 반환한다."""

        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        if samples.size == 0:
            return ProsodyMetadata(None, 0.0, "normal", "neutral", 0.0)

        normalized = samples / 32768.0
        rms = float(np.sqrt(np.mean(normalized * normalized)))
        pitch = self._estimate_pitch(normalized)

        # zero crossing density는 정확한 음절률 대신 빠르기 변화만 전달하는 저비용 힌트다.
        crossings = float(np.mean(np.abs(np.diff(np.signbit(normalized))))) if samples.size > 1 else 0.0
        pace: Literal["slow", "normal", "fast"]
        if crossings < 0.035:
            pace = "slow"
        elif crossings > 0.11:
            pace = "fast"
        else:
            pace = "normal"

        # energy와 빠르기를 함께 사용하되 0~1로 제한해 LLM 문맥이 수치에 과민해지지 않게 한다.
        urgency = min(1.0, max(0.0, rms * 4.0 + crossings * 1.5))
        emotion: Literal["calm", "neutral", "urgent"]
        if urgency >= 0.72:
            emotion = "urgent"
        elif urgency <= 0.20:
            emotion = "calm"
        else:
            emotion = "neutral"
        return ProsodyMetadata(
            pitch_mean_hz=round(pitch, 1) if pitch else None,
            rms_energy=round(rms, 4),
            speech_rate_hint=pace,
            emotion_hint=emotion,
            urgency=round(urgency, 2),
        )

    def _estimate_pitch(self, samples: np.ndarray) -> Optional[float]:
        """중앙 80 ms 구간의 autocorrelation peak로 대략적인 F0를 계산한다."""

        window_size = min(samples.size, int(self.sample_rate * 0.08))
        if window_size < int(self.sample_rate * 0.03):
            return None
        start = max(0, (samples.size - window_size) // 2)
        window = samples[start : start + window_size]
        window = window - float(np.mean(window))
        if float(np.max(np.abs(window))) < 0.01:
            return None
        correlation = np.correlate(window, window, mode="full")[window.size - 1 :]
        min_lag = max(1, math.floor(self.sample_rate / 350))
        max_lag = min(correlation.size - 1, math.ceil(self.sample_rate / 70))
        if max_lag <= min_lag:
            return None
        lag = min_lag + int(np.argmax(correlation[min_lag : max_lag + 1]))
        return self.sample_rate / lag if lag else None
