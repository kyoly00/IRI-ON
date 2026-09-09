"""Optional deep-learning noise suppression and anti-alias resampling.

The runtime only depends on :class:`NoiseSuppressor`. Native RNNoise and
DeepFilterNet imports are lazy, so the default browser mode keeps the existing
installation and startup path unchanged.
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
    """Base error raised at the optional native noise-suppression boundary."""


class NoiseSuppressorUnavailable(NoiseSuppressionError):
    """Raised when a selected native model or library is not installed."""


@dataclass(frozen=True)
class AudioFrame:
    """One mono PCM16 transport frame with correlation metadata."""

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
    """Runtime cost accumulated for trace/evaluator comparison."""

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
class NoiseSuppressor(Protocol):
    """Backend-independent asynchronous noise-suppression contract."""

    mode: str
    stats: NoiseSuppressionStats

    async def process(self, audio_frame: AudioFrame) -> AudioFrame:
        """Return a frame with the same sample-rate/time contract."""

    async def close(self) -> None:
        """Release native model state owned by one voice session."""


class PassthroughNoiseSuppressor:
    """No-op implementation used by ``none`` and browser NS modes."""

    def __init__(self, mode: str = "browser") -> None:
        self.mode = mode
        self.stats = NoiseSuppressionStats(mode=mode)

    async def process(self, audio_frame: AudioFrame) -> AudioFrame:
        started = time.perf_counter()
        self.stats.record(audio_frame, (time.perf_counter() - started) * 1000.0, 0.0)
        return audio_frame

    async def close(self) -> None:
        return None


class _MeasuredSuppressor:
    """Runs CPU-bound native inference off the event loop and records its cost."""

    mode = "unknown"

    def __init__(self) -> None:
        self.stats = NoiseSuppressionStats(mode=self.mode)

    async def process(self, audio_frame: AudioFrame) -> AudioFrame:
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
        raise NotImplementedError

    async def close(self) -> None:
        return None


class RNNoiseSuppressor(_MeasuredSuppressor):
    """RNNoise adapter for its native 48 kHz, 480-sample processing frames."""

    mode = "rnnoise"
    native_sample_rate = 48_000
    native_frame_samples = 480

    def __init__(
        self,
        library_path: str | None = None,
        native_processor: Callable[[np.ndarray], np.ndarray] | None = None,
    ) -> None:
        super().__init__()
        self._native_processor = native_processor
        self._library: ctypes.CDLL | None = None
        self._state: int | None = None
        if native_processor is None:
            self._load_library(library_path)

    def _load_library(self, library_path: str | None) -> None:
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
        if self._library is not None and self._state is not None:
            self._library.rnnoise_destroy(self._state)
        self._state = None
        self._library = None


class DeepFilterNetSuppressor(_MeasuredSuppressor):
    """Lazy DeepFilterNet adapter operating on full-band 48 kHz PCM frames.

    ``processor`` is an injection seam for tests or an optimized streaming
    binding. Without it, the official ``df.enhance`` Python package is loaded.
    """

    mode = "deepfilternet"
    native_sample_rate = 48_000

    def __init__(
        self,
        model_path: str | None = None,
        processor: Callable[[np.ndarray], np.ndarray] | None = None,
    ) -> None:
        super().__init__()
        self._model_path = model_path
        self._processor = processor
        self._model = None
        self._df_state = None

    def _load_model(self) -> None:
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
            audio = torch.from_numpy((samples / 32768.0).astype(np.float32)).unsqueeze(0)
            result = enhance(model, df_state, audio, pad=True).squeeze(0).numpy()
            return np.asarray(result * 32768.0, dtype=np.float32)

        self._processor = process_with_official_package

    def _process_sync(self, audio_frame: AudioFrame) -> AudioFrame:
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
    """Stateful windowed-sinc FIR decimator used after deep NS (48→16 kHz)."""

    def __init__(self, source_rate: int, target_rate: int, taps: int = 63) -> None:
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
    """Build the selected implementation while keeping optional imports lazy."""

    normalized = mode.strip().lower()
    if normalized in {"none", "browser"}:
        return PassthroughNoiseSuppressor(normalized)
    if normalized == "rnnoise":
        return RNNoiseSuppressor(rnnoise_library)
    if normalized == "deepfilternet":
        return DeepFilterNetSuppressor(deepfilternet_model)
    raise ValueError(f"Unsupported noise suppression mode: {mode}")
