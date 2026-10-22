"""Streaming LLM text를 자연스러운 TTS 요청과 연속 PCM으로 변환하는 도구."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time
from typing import Optional

import numpy as np


_SENTENCE_END = frozenset(".!?。！？\n~")
_CLAUSE_END = frozenset(",;:，；：、…")
_KOREAN_CLAUSE = re.compile(
    r"(?:지만|는데|하고|해서|하며|면|고|다가|거나|부터|까지|다음에|그다음에)\s+$"
)


@dataclass(frozen=True)
class TTSChunkPolicy:
    """글자 수를 강제 절단점이 아닌 latency/안전 길이 힌트로 사용한다."""

    preferred_min_chars: int = 24
    target_chars: int = 64
    maximum_chars: int = 180
    maximum_latency_ms: int = 550
    first_min_chars: int = 12
    first_maximum_latency_ms: int = 380


@dataclass(frozen=True)
class ScheduledTextChunk:
    text: str
    boundary: str
    buffered_ms: float


class TTSChunkScheduler:
    """문장→구두점→구문→공백 순으로 TTS 경계를 선택하는 incremental scheduler."""

    def __init__(self, policy: TTSChunkPolicy | None = None) -> None:
        self.policy = policy or TTSChunkPolicy()
        self._buffer = ""
        self._buffered_at: float | None = None
        self._chunks_emitted = 0

    @property
    def has_pending_text(self) -> bool:
        return bool(self._buffer.strip())

    def seconds_until_deadline(self, now: float | None = None) -> float | None:
        if self._buffered_at is None or not self.has_pending_text:
            return None
        elapsed = (now if now is not None else time.monotonic()) - self._buffered_at
        limit = (
            self.policy.first_maximum_latency_ms
            if self._chunks_emitted == 0
            else self.policy.maximum_latency_ms
        )
        return max(0.0, limit / 1000.0 - elapsed)

    def feed(self, delta: str, now: float | None = None) -> list[ScheduledTextChunk]:
        current = now if now is not None else time.monotonic()
        if delta:
            if not self.has_pending_text:
                self._buffered_at = current
            self._buffer += delta

        chunks: list[ScheduledTextChunk] = []
        while self.has_pending_text:
            boundary = self._select_boundary(force_latency=False)
            if boundary is None:
                break
            split_at, kind = boundary
            chunks.append(self._take(split_at, kind, current))
        return chunks

    def flush_due(self, now: float | None = None) -> Optional[ScheduledTextChunk]:
        current = now if now is not None else time.monotonic()
        deadline = self.seconds_until_deadline(current)
        if deadline is None or deadline > 0:
            return None
        boundary = self._select_boundary(force_latency=True)
        if boundary is None:
            # 첫 청크가 아직 너무 짧으면 다음 token을 기다린다. deadline을 그대로
            # 0에 두면 runtime의 asyncio.wait(timeout=0)가 busy-loop에 빠질 수 있다.
            self._buffered_at = current
            return None
        split_at, kind = boundary
        return self._take(split_at, f"latency_{kind}", current)

    def flush(self, now: float | None = None) -> Optional[ScheduledTextChunk]:
        if not self.has_pending_text:
            self._reset()
            return None
        current = now if now is not None else time.monotonic()
        return self._take(len(self._buffer), "stream_end", current)

    def _select_boundary(self, *, force_latency: bool) -> tuple[int, str] | None:
        text = self._buffer
        length = len(text)
        if not text.strip():
            self._reset()
            return None

        preferred = self.policy.preferred_min_chars
        minimum = self.policy.first_min_chars if self._chunks_emitted == 0 else preferred
        target = min(self.policy.target_chars, length)

        # 완성된 문장은 가장 높은 우선순위다. 짧은 문장은 다음 의미 단위와 합쳐
        # 독립 TTS 요청에서 운율이 매번 초기화되는 횟수를 줄인다.
        sentence = self._last_boundary(
            _SENTENCE_END,
            minimum,
            min(length, self.policy.maximum_chars),
        )
        if sentence is not None and sentence >= minimum:
            return sentence, "sentence"

        if length >= self.policy.target_chars or force_latency:
            clause = self._last_boundary(_CLAUSE_END, minimum, target)
            if clause is not None:
                return clause, "punctuation"

            syntax = self._last_korean_clause(target)
            if syntax is not None and syntax >= minimum:
                return syntax, "clause"

            whitespace = text.rfind(" ", 0, target + 1)
            if whitespace >= minimum:
                return whitespace + 1, "whitespace"

        if length >= self.policy.maximum_chars:
            whitespace = text.rfind(" ", 0, self.policy.maximum_chars + 1)
            if whitespace > 0:
                return whitespace + 1, "maximum_whitespace"
            return self.policy.maximum_chars, "maximum_hard"
        return None

    def _last_boundary(self, characters: frozenset[str], minimum: int, maximum: int) -> int | None:
        upper = min(maximum, len(self._buffer))
        for index in range(upper, max(0, minimum - 1), -1):
            if self._buffer[index - 1] in characters:
                return index
        return None

    def _last_korean_clause(self, maximum: int) -> int | None:
        prefix = self._buffer[:maximum]
        matches = list(_KOREAN_CLAUSE.finditer(prefix))
        return matches[-1].end() if matches else None

    def _take(self, split_at: int, boundary: str, now: float) -> ScheduledTextChunk:
        text = self._buffer[:split_at].strip()
        buffered_ms = max(0.0, (now - (self._buffered_at or now)) * 1000.0)
        self._buffer = self._buffer[split_at:].lstrip()
        self._buffered_at = now if self.has_pending_text else None
        self._chunks_emitted += 1
        return ScheduledTextChunk(text=text, boundary=boundary, buffered_ms=buffered_ms)

    def _reset(self) -> None:
        self._buffer = ""
        self._buffered_at = None
        self._chunks_emitted = 0


@dataclass(frozen=True)
class PCMBoundaryMetrics:
    jump: float
    rms_ratio_db: float
    leading_silence_ms: float
    trailing_silence_ms: float


def inspect_pcm_boundary(
    previous_pcm: bytes,
    current_pcm: bytes,
    sample_rate: int,
    silence_threshold: float = 0.003,
) -> PCMBoundaryMetrics:
    """두 독립 TTS 요청 사이의 파형 불연속·음량 변화·무음을 측정한다."""

    previous = np.frombuffer(previous_pcm, dtype="<i2").astype(np.float32) / 32768.0
    current = np.frombuffer(current_pcm, dtype="<i2").astype(np.float32) / 32768.0
    jump = float(abs(current[0] - previous[-1])) if previous.size and current.size else 0.0

    window = max(1, min(previous.size, current.size, int(sample_rate * 0.05)))
    prev_rms = float(np.sqrt(np.mean(previous[-window:] ** 2))) if previous.size else 0.0
    curr_rms = float(np.sqrt(np.mean(current[:window] ** 2))) if current.size else 0.0
    rms_ratio_db = 20.0 * math.log10((curr_rms + 1e-7) / (prev_rms + 1e-7))

    leading = _edge_silence_samples(current, silence_threshold, from_start=True)
    trailing = _edge_silence_samples(previous, silence_threshold, from_start=False)
    return PCMBoundaryMetrics(
        jump=jump,
        rms_ratio_db=rms_ratio_db,
        leading_silence_ms=leading / sample_rate * 1000.0,
        trailing_silence_ms=trailing / sample_rate * 1000.0,
    )


def stitch_pcm_boundary(
    previous_tail: bytes,
    current_head: bytes,
    sample_rate: int,
    *,
    crossfade_ms: float = 5.0,
    silence_threshold: float = 0.003,
    jump_threshold: float = 0.08,
) -> tuple[bytes, PCMBoundaryMetrics, bool]:
    """독립 합성 경계만 검사하고 클릭 위험이 있을 때에만 짧게 crossfade한다."""

    metrics = inspect_pcm_boundary(previous_tail, current_head, sample_rate, silence_threshold)
    previous = np.frombuffer(previous_tail, dtype="<i2").copy()
    current = np.frombuffer(current_head, dtype="<i2").copy()

    trailing = min(previous.size, round(metrics.trailing_silence_ms * sample_rate / 1000.0))
    leading = min(current.size, round(metrics.leading_silence_ms * sample_rate / 1000.0))
    if trailing:
        previous = previous[:-trailing]
    if leading:
        current = current[leading:]

    fade_samples = min(previous.size, current.size, max(1, round(sample_rate * crossfade_ms / 1000.0)))
    should_crossfade = metrics.jump >= jump_threshold and fade_samples > 1
    if not should_crossfade:
        return previous.astype("<i2").tobytes() + current.astype("<i2").tobytes(), metrics, False

    fade_out = np.linspace(1.0, 0.0, fade_samples, endpoint=False, dtype=np.float32)
    fade_in = 1.0 - fade_out
    mixed = (
        previous[-fade_samples:].astype(np.float32) * fade_out
        + current[:fade_samples].astype(np.float32) * fade_in
    )
    mixed = np.clip(np.rint(mixed), -32768, 32767).astype("<i2")
    stitched = np.concatenate((previous[:-fade_samples], mixed, current[fade_samples:]))
    return stitched.astype("<i2").tobytes(), metrics, True


def fade_out_pcm(pcm: bytes, sample_rate: int, fade_ms: float = 5.0) -> bytes:
    """실제 응답 끝에서만 non-zero 마지막 sample을 부드럽게 0으로 내린다."""

    samples = np.frombuffer(pcm, dtype="<i2").copy()
    count = min(samples.size, max(1, round(sample_rate * fade_ms / 1000.0)))
    if count <= 1 or not samples.size or abs(int(samples[-1])) < 64:
        return pcm
    ramp = np.linspace(1.0, 0.0, count, dtype=np.float32)
    samples[-count:] = np.clip(np.rint(samples[-count:].astype(np.float32) * ramp), -32768, 32767).astype("<i2")
    return samples.astype("<i2").tobytes()


def _edge_silence_samples(samples: np.ndarray, threshold: float, *, from_start: bool) -> int:
    if not samples.size:
        return 0
    mask = np.abs(samples) > threshold
    indices = np.flatnonzero(mask)
    if not indices.size:
        return int(samples.size)
    return int(indices[0] if from_start else samples.size - indices[-1] - 1)
