"""선택형 딥러닝 노이즈 억제와 안티앨리어싱 리샘플링을 제공한다.

런타임은 :class:`NoiseSuppressor` 추상 계약에만 의존한다. RNNoise 네이티브
라이브러리와 DeepFilterNet 패키지는 실제로 해당 모드를 선택할 때만 지연
로딩하므로, 기본 browser 모드의 설치 및 시작 경로에는 영향을 주지 않는다.
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable, Protocol, runtime_checkable

import numpy as np


class NoiseSuppressionError(RuntimeError):
    """선택형 네이티브 노이즈 억제 경계에서 발생하는 공통 오류다."""


class NoiseSuppressorUnavailable(NoiseSuppressionError):
    """선택한 네이티브 모델 또는 라이브러리를 사용할 수 없을 때 발생한다."""


@dataclass(frozen=True)
class AudioFrame:
    """상관관계 추적 메타데이터를 포함한 모노 PCM16 전송 프레임 하나다."""

    pcm: bytes
    sample_rate: int
    sequence: int
    sample_index: int
    timestamp: float

    @property
    def samples(self) -> int:
        """PCM16 바이트 길이를 샘플 개수로 변환한다."""

        return len(self.pcm) // 2

    @property
    def duration_ms(self) -> float:
        """현재 프레임의 재생 시간을 밀리초로 반환한다."""

        return self.samples / self.sample_rate * 1000.0 if self.sample_rate else 0.0


@dataclass
class NoiseSuppressionStats:
    """trace 및 evaluator 비교를 위해 세션 동안 누적하는 실행 비용이다."""

    mode: str
    frames: int = 0
    audio_ms: float = 0.0
    processing_ms: float = 0.0
    cpu_ms: float = 0.0
    max_frame_latency_ms: float = 0.0
    failures: int = 0

    def record(self, frame: AudioFrame, wall_ms: float, cpu_ms: float) -> None:
        """프레임 하나의 음성 길이, 처리 지연시간과 CPU 시간을 누적한다."""

        self.frames += 1
        self.audio_ms += frame.duration_ms
        self.processing_ms += wall_ms
        self.cpu_ms += cpu_ms
        self.max_frame_latency_ms = max(self.max_frame_latency_ms, wall_ms)

    def summary(self) -> dict[str, float | int | str]:
        """누적값을 평균 지연시간, RTF, 처리 중 CPU 사용률로 요약한다."""

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
class NoiseSuppressor(Protocol):
    """구현 backend와 무관하게 런타임이 사용하는 비동기 노이즈 억제 계약이다."""

    mode: str
    stats: NoiseSuppressionStats

    async def process(self, audio_frame: AudioFrame) -> AudioFrame:
        """동일한 sample-rate 및 시간축 계약을 유지한 처리 프레임을 반환한다."""

    async def close(self) -> None:
        """음성 세션 하나가 소유한 네이티브 모델 상태를 해제한다."""


class PassthroughNoiseSuppressor:
    """``none``과 browser NS 모드에서 사용하는 무처리 구현이다."""

    def __init__(self, mode: str = "browser") -> None:
        """선택된 모드 이름을 보존하고 통계 누적기를 만든다."""

        self.mode = mode
        self.stats = NoiseSuppressionStats(mode=mode)

    async def process(self, audio_frame: AudioFrame) -> AudioFrame:
        """프레임을 변경하지 않고 무처리 비용만 기록해 반환한다."""

        started = time.perf_counter()
        self.stats.record(audio_frame, (time.perf_counter() - started) * 1000.0, 0.0)
        return audio_frame

    async def close(self) -> None:
        """해제할 외부 자원이 없으므로 아무 작업도 하지 않는다."""

        return None


class _MeasuredSuppressor:
    """CPU 중심 네이티브 추론을 event loop 밖에서 실행하고 비용을 기록한다."""

    mode = "unknown"

    def __init__(self) -> None:
        """구현 클래스의 mode에 대응하는 통계 누적기를 만든다."""

        self.stats = NoiseSuppressionStats(mode=self.mode)

    async def process(self, audio_frame: AudioFrame) -> AudioFrame:
        """동기 추론을 작업 스레드에서 실행하고 wall/CPU 시간을 측정한다."""

        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        try:
            processed = await asyncio.to_thread(self._process_sync, audio_frame)
        except Exception:
            self.stats.failures += 1
            raise
        self.stats.record(
            audio_frame,
            (time.perf_counter() - wall_started) * 1000.0,
            (time.process_time() - cpu_started) * 1000.0,
        )
        return processed

    def _process_sync(self, audio_frame: AudioFrame) -> AudioFrame:
        """구현 클래스가 제공해야 하는 동기 프레임 처리 지점이다."""

        raise NotImplementedError

    async def close(self) -> None:
        """기본 구현에는 해제할 자원이 없으며 구현 클래스가 필요 시 재정의한다."""

        return None


class RNNoiseSuppressor(_MeasuredSuppressor):
    """RNNoise의 네이티브 48 kHz, 480샘플 처리 규격을 연결하는 adapter다."""

    mode = "rnnoise"
    native_sample_rate = 48_000
    native_frame_samples = 480

    def __init__(
        self,
        library_path: str | None = None,
        native_processor: Callable[[np.ndarray], np.ndarray] | None = None,
    ) -> None:
        """주입된 processor를 쓰거나 지정된 RNNoise 라이브러리를 로딩한다."""

        super().__init__()
        self._native_processor = native_processor
        self._library: ctypes.CDLL | None = None
        self._state: int | None = None
        if native_processor is None:
            self._load_library(library_path)

    def _load_library(self, library_path: str | None) -> None:
        """RNNoise 공유 라이브러리의 C ABI를 설정하고 세션 상태를 생성한다."""

        resolved = library_path or ctypes.util.find_library("rnnoise")
        if not resolved:
            raise NoiseSuppressorUnavailable(
                "RNNoise native library was not found. Set CUSTOM_VOICE_RNNOISE_LIBRARY "
                "to rnnoise.dll/librnnoise.so."
            )
        try:
            library = ctypes.CDLL(str(Path(resolved)))
        except OSError as exc:
            raise NoiseSuppressorUnavailable(f"Unable to load RNNoise library: {resolved}") from exc
        library.rnnoise_create.argtypes = [ctypes.c_void_p]
        library.rnnoise_create.restype = ctypes.c_void_p
        library.rnnoise_destroy.argtypes = [ctypes.c_void_p]
        library.rnnoise_process_frame.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
        ]
        library.rnnoise_process_frame.restype = ctypes.c_float
        state = library.rnnoise_create(None)
        if not state:
            raise NoiseSuppressorUnavailable("RNNoise failed to create a denoising state")
        self._library = library
        self._state = state

    def _process_native_block(self, samples: np.ndarray) -> np.ndarray:
        """정확히 480개 샘플을 주입 processor 또는 RNNoise C 함수로 처리한다."""

        if self._native_processor is not None:
            result = np.asarray(self._native_processor(samples.copy()), dtype=np.float32)
            if result.shape != samples.shape:
                raise NoiseSuppressionError("RNNoise processor changed the 480-sample frame size")
            return result
        if self._library is None or self._state is None:
            raise NoiseSuppressorUnavailable("RNNoise state is closed")
        buffer = (ctypes.c_float * self.native_frame_samples)(*samples.tolist())
        self._library.rnnoise_process_frame(self._state, buffer, buffer)
        return np.ctypeslib.as_array(buffer).copy()

    def _process_sync(self, audio_frame: AudioFrame) -> AudioFrame:
        """48 kHz 전송 프레임을 480샘플 블록으로 나눠 순차 처리한다."""

        if audio_frame.sample_rate != self.native_sample_rate:
            raise NoiseSuppressionError("RNNoise input must be 48 kHz PCM16 before downsampling")
        samples = np.frombuffer(audio_frame.pcm, dtype="<i2").astype(np.float32)
        if samples.size % self.native_frame_samples:
            raise NoiseSuppressionError("RNNoise input must contain whole 480-sample native frames")
        enhanced = np.empty_like(samples)
        for offset in range(0, samples.size, self.native_frame_samples):
            enhanced[offset : offset + self.native_frame_samples] = self._process_native_block(
                samples[offset : offset + self.native_frame_samples]
            )
        pcm = np.clip(np.rint(enhanced), -32768, 32767).astype("<i2").tobytes()
        return AudioFrame(pcm, audio_frame.sample_rate, audio_frame.sequence, audio_frame.sample_index, audio_frame.timestamp)

    async def close(self) -> None:
        """RNNoise 세션 상태를 파괴하고 공유 라이브러리 참조를 해제한다."""

        if self._library is not None and self._state is not None:
            self._library.rnnoise_destroy(self._state)
        self._state = None
        self._library = None


class DeepFilterNetSuppressor(_MeasuredSuppressor):
    """전대역 48 kHz PCM 프레임을 처리하는 지연 로딩 DeepFilterNet adapter다.

    ``processor``는 테스트 또는 최적화된 streaming binding을 주입하는 경계다.
    이를 전달하지 않으면 공식 ``df.enhance`` Python 패키지를 로딩한다.
    """

    mode = "deepfilternet"
    native_sample_rate = 48_000

    def __init__(
        self,
        model_path: str | None = None,
        processor: Callable[[np.ndarray], np.ndarray] | None = None,
    ) -> None:
        """모델 경로와 선택적 processor를 보관하며 모델 로딩은 미룬다."""

        super().__init__()
        self._model_path = model_path
        self._processor = processor
        self._model = None
        self._df_state = None

    def _load_model(self) -> None:
        """첫 처리 요청에서 DeepFilterNet 모델과 상태를 한 번만 로딩한다."""

        if self._processor is not None or self._model is not None:
            return
        try:
            import torch
            from df.enhance import enhance, init_df
        except ImportError as exc:
            raise NoiseSuppressorUnavailable(
                "DeepFilterNet is not installed. Install the optional DeepFilterNet package "
                "or select CUSTOM_VOICE_NOISE_SUPPRESSION=browser."
            ) from exc
        model, df_state, _suffix, _epoch = init_df(
            self._model_path,
            log_level="ERROR",
            log_file=None,
            config_allow_defaults=True,
        )
        self._model = model
        self._df_state = df_state

        def process_with_official_package(samples: np.ndarray) -> np.ndarray:
            """PCM16 범위 샘플을 tensor로 정규화해 공식 enhance 함수를 호출한다."""

            audio = torch.from_numpy((samples / 32768.0).astype(np.float32)).unsqueeze(0)
            result = enhance(model, df_state, audio, pad=True).squeeze(0).numpy()
            return np.asarray(result * 32768.0, dtype=np.float32)

        self._processor = process_with_official_package

    def _process_sync(self, audio_frame: AudioFrame) -> AudioFrame:
        """48 kHz 프레임을 DeepFilterNet으로 처리하고 PCM16 범위로 복원한다."""

        if audio_frame.sample_rate != self.native_sample_rate:
            raise NoiseSuppressionError("DeepFilterNet input must be 48 kHz PCM16 before downsampling")
        self._load_model()
        assert self._processor is not None
        samples = np.frombuffer(audio_frame.pcm, dtype="<i2").astype(np.float32)
        enhanced = np.asarray(self._processor(samples.copy()), dtype=np.float32).reshape(-1)
        if enhanced.size != samples.size:
            raise NoiseSuppressionError("DeepFilterNet processor changed the transport frame size")
        pcm = np.clip(np.rint(enhanced), -32768, 32767).astype("<i2").tobytes()
        return AudioFrame(pcm, audio_frame.sample_rate, audio_frame.sequence, audio_frame.sample_index, audio_frame.timestamp)


class AntiAliasResampler:
    """Deep NS 이후 48→16 kHz 변환에 쓰는 상태 유지형 windowed-sinc FIR decimator다."""

    def __init__(self, source_rate: int, target_rate: int, taps: int = 63) -> None:
        """정수 downsampling 배율을 검증하고 저역통과 FIR kernel을 생성한다."""

        if source_rate == target_rate:
            self.factor = 1
        elif source_rate % target_rate == 0:
            self.factor = source_rate // target_rate
        else:
            raise ValueError("AntiAliasResampler currently requires an integer downsampling ratio")
        if taps < 3 or taps % 2 == 0:
            raise ValueError("FIR tap count must be an odd integer >= 3")
        self.source_rate = source_rate
        self.target_rate = target_rate
        self._history = np.zeros(taps - 1, dtype=np.float32)
        if self.factor == 1:
            self._kernel = np.array([1.0], dtype=np.float32)
            self._history = np.empty(0, dtype=np.float32)
        else:
            positions = np.arange(taps, dtype=np.float64) - (taps - 1) / 2
            cutoff = 0.45 / self.factor
            kernel = 2 * cutoff * np.sinc(2 * cutoff * positions) * np.hamming(taps)
            self._kernel = (kernel / np.sum(kernel)).astype(np.float32)

    def process(self, audio_frame: AudioFrame) -> AudioFrame:
        """이전 프레임 이력을 이어 필터링한 뒤 목표 sample rate로 decimation한다."""

        if audio_frame.sample_rate != self.source_rate:
            raise ValueError(f"Expected {self.source_rate} Hz input, got {audio_frame.sample_rate} Hz")
        if self.factor == 1:
            return audio_frame
        samples = np.frombuffer(audio_frame.pcm, dtype="<i2").astype(np.float32)
        extended = np.concatenate((self._history, samples))
        filtered = np.convolve(extended, self._kernel, mode="valid")
        self._history = extended[-(self._kernel.size - 1) :]
        downsampled = filtered[:: self.factor]
        pcm = np.clip(np.rint(downsampled), -32768, 32767).astype("<i2").tobytes()
        return AudioFrame(
            pcm=pcm,
            sample_rate=self.target_rate,
            sequence=audio_frame.sequence,
            sample_index=audio_frame.sample_index // self.factor,
            timestamp=audio_frame.timestamp,
        )


def create_noise_suppressor(
    mode: str,
    *,
    rnnoise_library: str | None = None,
    deepfilternet_model: str | None = None,
) -> NoiseSuppressor:
    """선택 모드의 구현을 만들되 선택형 의존성은 계속 지연 로딩한다."""

    normalized = mode.strip().lower()
    if normalized in {"none", "browser"}:
        return PassthroughNoiseSuppressor(normalized)
    if normalized == "rnnoise":
        return RNNoiseSuppressor(rnnoise_library)
    if normalized == "deepfilternet":
        return DeepFilterNetSuppressor(deepfilternet_model)
    raise ValueError(f"Unsupported noise suppression mode: {mode}")
