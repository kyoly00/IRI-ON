"""교체 가능한 final/partial STT 엔진과 faster-whisper 선택 백엔드."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import threading
from typing import Any, Protocol

import numpy as np

from .config import CustomVoiceSettings


logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class STTSegment:
    start_ms: float
    end_ms: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    speaker: str = "unknown_speaker"


@dataclass(frozen=True)
class STTResult:
    text: str
    segments: list[STTSegment] = field(default_factory=list)
    language: str = "ko"
    is_final: bool = True


class STTEngine(Protocol):
    async def transcribe(self, pcm: bytes, prompt: str | None = None, *, partial: bool = False) -> STTResult: ...


class ProviderSTTEngine:
    """기존 원격 STT provider를 동일 인터페이스로 보존한다."""

    def __init__(self, provider: Any) -> None:
        self.provider = provider

    async def transcribe(self, pcm: bytes, prompt: str | None = None, *, partial: bool = False) -> STTResult:
        text = await self.provider.transcribe(pcm, prompt=prompt)
        duration_ms = len(pcm) / 2 / 16_000 * 1000.0
        segments = [STTSegment(0.0, duration_ms, text)] if text else []
        return STTResult(text=text, segments=segments, is_final=not partial)


_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}
_MODEL_LOCK = threading.Lock()


class FasterWhisperSTTEngine:
    """VAD가 확정한 16 kHz mono PCM만 처리하는 비동기 faster-whisper adapter."""

    def __init__(self, settings: CustomVoiceSettings) -> None:
        self.settings = settings
        self._model_key = (
            settings.faster_whisper_model,
            settings.faster_whisper_device,
            settings.faster_whisper_compute_type,
        )

    def _get_model(self):
        with _MODEL_LOCK:
            model = _MODEL_CACHE.get(self._model_key)
            if model is not None:
                return model
            from faster_whisper import WhisperModel

            model_name, device, compute_type = self._model_key
            kwargs: dict[str, Any] = {"device": device}
            if compute_type != "default":
                kwargs["compute_type"] = compute_type
            model = WhisperModel(model_name, **kwargs)
            _MODEL_CACHE[self._model_key] = model
            return model

    async def transcribe(self, pcm: bytes, prompt: str | None = None, *, partial: bool = False) -> STTResult:
        return await asyncio.to_thread(self._transcribe_sync, pcm, prompt, partial)

    def _transcribe_sync(self, pcm: bytes, prompt: str | None, partial: bool) -> STTResult:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if not samples.size:
            return STTResult(text="", is_final=not partial)
        model = self._get_model()
        segments_iter, info = model.transcribe(
            samples,
            language="ko",
            initial_prompt=prompt,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=True,
            no_speech_threshold=0.6,
            hallucination_silence_threshold=1.0,
            beam_size=1 if partial else 5,
        )
        segments: list[STTSegment] = []
        texts: list[str] = []
        for segment in segments_iter:
            text = str(segment.text or "").strip()
            no_speech_prob = getattr(segment, "no_speech_prob", None)
            avg_logprob = getattr(segment, "avg_logprob", None)
            if not text or (no_speech_prob is not None and no_speech_prob >= 0.8):
                continue
            if texts and _normalized_overlap(texts[-1], text) >= 0.9:
                continue
            texts.append(text)
            segments.append(
                STTSegment(
                    start_ms=float(segment.start) * 1000.0,
                    end_ms=float(segment.end) * 1000.0,
                    text=text,
                    avg_logprob=float(avg_logprob) if avg_logprob is not None else None,
                    no_speech_prob=float(no_speech_prob) if no_speech_prob is not None else None,
                )
            )
        return STTResult(
            text=" ".join(texts).strip(),
            segments=segments,
            language=str(getattr(info, "language", "ko") or "ko"),
            is_final=not partial,
        )


class ResilientSTTEngine:
    """로컬 모델 로드/OOM 실패 뒤 같은 발화를 원격 STT로 안전하게 재시도한다."""

    def __init__(self, primary: STTEngine, fallback: STTEngine) -> None:
        self.primary = primary
        self.fallback = fallback
        self.degraded = False

    async def transcribe(self, pcm: bytes, prompt: str | None = None, *, partial: bool = False) -> STTResult:
        if self.degraded:
            return await self.fallback.transcribe(pcm, prompt=prompt, partial=partial)
        try:
            return await self.primary.transcribe(pcm, prompt=prompt, partial=partial)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.degraded = True
            logger.warning("[CustomVoice] local STT failed (%s); degrading to remote provider", exc)
            return await self.fallback.transcribe(pcm, prompt=prompt, partial=partial)


def create_stt_engine(settings: CustomVoiceSettings, provider: Any) -> STTEngine:
    if settings.stt_backend != "faster_whisper":
        return ProviderSTTEngine(provider)
    try:
        import faster_whisper  # noqa: F401

        return ResilientSTTEngine(FasterWhisperSTTEngine(settings), ProviderSTTEngine(provider))
    except Exception as exc:
        logger.warning(
            "[CustomVoice] faster-whisper unavailable (%s); using configured remote STT provider",
            exc,
        )
        return ProviderSTTEngine(provider)


def _normalized_overlap(previous: str, current: str) -> float:
    left = "".join(previous.split())
    right = "".join(current.split())
    if not left or not right:
        return 0.0
    maximum = min(len(left), len(right))
    overlap = 0
    for size in range(1, maximum + 1):
        if left[-size:] == right[:size]:
            overlap = size
    return overlap / max(1, min(len(left), len(right)))
