"""오디오 전처리 구현과 런타임 사이의 안정적인 엔진 계약.

구체적인 RNNoise/DeepFilterNet 구현은 ``noise_suppression`` 모듈에 남기고,
런타임과 평가기는 이 모듈의 데이터/수명주기 계약만 바라본다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class NoiseSuppressionError(RuntimeError):
    """잡음 제거 엔진 경계에서 발생하는 공통 오류."""


class NoiseSuppressorUnavailable(NoiseSuppressionError):
    """선택한 엔진이나 모델을 현재 환경에서 사용할 수 없을 때 발생한다."""


@dataclass(frozen=True)
class AudioFrame:
    """상관관계 추적 메타데이터를 포함한 모노 PCM16 프레임."""

    pcm: bytes
    sample_rate: int
    sequence: int
    sample_index: int
    timestamp: float

    @property
    def samples(self) -> int:
        return len(self.pcm) // 2

    @property
    def duration_ms(self) -> float:
        return self.samples / self.sample_rate * 1000.0 if self.sample_rate else 0.0


@dataclass
class NoiseSuppressionStats:
    """세션 단위 엔진 처리량과 비용."""

    mode: str
    frames: int = 0
    audio_ms: float = 0.0
    processing_ms: float = 0.0
    cpu_ms: float = 0.0
    max_frame_latency_ms: float = 0.0
    failures: int = 0

    def record(self, frame: AudioFrame, wall_ms: float, cpu_ms: float) -> None:
        self.frames += 1
        self.audio_ms += frame.duration_ms
        self.processing_ms += wall_ms
        self.cpu_ms += cpu_ms
        self.max_frame_latency_ms = max(self.max_frame_latency_ms, wall_ms)

    def summary(self) -> dict[str, float | int | str]:
        mean_ms = self.processing_ms / self.frames if self.frames else 0.0
        rtf = self.processing_ms / self.audio_ms if self.audio_ms else 0.0
        cpu_usage = self.cpu_ms / self.processing_ms * 100.0 if self.processing_ms else 0.0
        return {
            "mode": self.mode,
            "frames": self.frames,
            "audio_ms": round(self.audio_ms, 3),
            "processing_latency_ms_mean": round(mean_ms, 3),
            "processing_latency_ms_max": round(self.max_frame_latency_ms, 3),
            "realtime_factor": round(rtf, 5),
            "cpu_usage_pct_during_processing": round(cpu_usage, 2),
            "failures": self.failures,
        }


@runtime_checkable
class NoiseSuppressionEngine(Protocol):
    """구현체와 무관하게 런타임이 의존하는 비동기 엔진 계약."""

    mode: str
    stats: NoiseSuppressionStats

    async def process(self, audio_frame: AudioFrame) -> AudioFrame:
        """sample-rate와 시간축을 유지한 처리 프레임을 반환한다."""

    async def close(self) -> None:
        """세션이 소유한 엔진 상태와 네이티브 자원을 해제한다."""


# 기존 import 사용처를 깨지 않기 위한 이름 호환성.
NoiseSuppressor = NoiseSuppressionEngine
