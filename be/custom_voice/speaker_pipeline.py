"""선택적 Streaming Sortformer diarization과 TitaNet speaker identification."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import logging
from pathlib import Path
import tempfile
import wave
from typing import Protocol

import numpy as np

from .config import CustomVoiceSettings


logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class SpeakerActivity:
    start_ms: float
    end_ms: float
    probabilities: tuple[float, ...]

    @property
    def speaker(self) -> str:
        if not self.probabilities:
            return "unknown_speaker"
        return f"speaker_{int(np.argmax(self.probabilities))}"


class SpeakerPipeline(Protocol):
    async def start(self) -> None: ...
    def submit(self, pcm: bytes) -> None: ...
    def dominant_recent(self, duration_ms: float) -> str: ...
    def labels_for_recent_segments(self, duration_ms: float, segments: list[tuple[float, float]]) -> list[str]: ...
    async def close(self) -> None: ...


class NullSpeakerPipeline:
    async def start(self) -> None:
        return None

    def submit(self, pcm: bytes) -> None:
        return None

    def dominant_recent(self, duration_ms: float) -> str:
        return "unknown_speaker"

    def labels_for_recent_segments(self, duration_ms: float, segments: list[tuple[float, float]]) -> list[str]:
        return ["unknown_speaker" for _ in segments]

    async def close(self) -> None:
        return None


class SortformerStreamingPipeline:
    """NeMo speaker cache/FIFO state를 세션 동안 유지하는 비차단 diarization worker."""

    def __init__(self, settings: CustomVoiceSettings) -> None:
        self.settings = settings
        self._input: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=100)
        self._worker: asyncio.Task[None] | None = None
        self._model = None
        self._torch = None
        self._state = None
        self._total_preds = None
        self._raw_buffer = np.empty(0, dtype=np.float32)
        self._activities: deque[SpeakerActivity] = deque(maxlen=3_600)
        self._processed_ms = 0.0
        self.dropped_frames = 0

    async def start(self) -> None:
        await asyncio.to_thread(self._load_model)
        self._worker = asyncio.create_task(self._run())

    def _load_model(self) -> None:
        import torch
        from nemo.collections.asr.models import SortformerEncLabelModel

        self._torch = torch
        model = SortformerEncLabelModel.from_pretrained(model_name=self.settings.sortformer_model)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device).eval()
        # NVIDIA model card의 low-latency 1.04 s geometry.
        model.sortformer_modules.chunk_len = 6
        model.sortformer_modules.chunk_right_context = 7
        model.sortformer_modules.fifo_len = 188
        model.sortformer_modules.spkcache_update_period = 144
        model.sortformer_modules.spkcache_len = 188
        model._check_streaming_parameters()
        self._model = model
        self._state = model.sortformer_modules.init_streaming_state(
            batch_size=1,
            async_streaming=model.async_streaming,
            device=model.device,
        )
        speakers = int(model.sortformer_modules.n_spk)
        self._total_preds = torch.empty((1, 0, speakers), device=model.device)

    def submit(self, pcm: bytes) -> None:
        if not pcm:
            return
        try:
            self._input.put_nowait(pcm)
        except asyncio.QueueFull:
            self.dropped_frames += 1

    async def _run(self) -> None:
        try:
            while True:
                pcm = await self._input.get()
                if pcm is None:
                    break
                samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
                self._raw_buffer = np.concatenate((self._raw_buffer, samples))
                # low-latency geometry: 480 ms output + 560 ms right context.
                while self._raw_buffer.size >= 16_640:
                    window = self._raw_buffer[:16_640].copy()
                    self._raw_buffer = self._raw_buffer[7_680:]
                    probabilities = await asyncio.to_thread(self._infer_window, window)
                    frame_ms = 480.0 / max(1, probabilities.shape[0])
                    for row in probabilities:
                        self._activities.append(
                            SpeakerActivity(
                                start_ms=self._processed_ms,
                                end_ms=self._processed_ms + frame_ms,
                                probabilities=tuple(float(value) for value in row),
                            )
                        )
                        self._processed_ms += frame_ms
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[CustomVoice] Streaming Sortformer worker failed; speaker labels disabled")

    def _infer_window(self, samples: np.ndarray) -> np.ndarray:
        torch = self._torch
        model = self._model
        audio = torch.from_numpy(samples).unsqueeze(0).to(model.device)
        length = torch.tensor([audio.shape[1]], dtype=torch.long, device=model.device)
        with torch.no_grad():
            processed, processed_length = model.process_signal(audio, length)
            offset = torch.zeros((1,), dtype=torch.long, device=model.device)
            loader = model.sortformer_modules.streaming_feat_loader(
                feat_seq=processed,
                feat_seq_length=processed_length,
                feat_seq_offset=offset,
            )
            _, chunk, chunk_lengths, left_offset, right_offset = next(iter(loader))
            previous_length = self._total_preds.shape[1]
            self._state, self._total_preds = model.forward_streaming_step(
                processed_signal=chunk,
                processed_signal_length=chunk_lengths,
                streaming_state=self._state,
                total_preds=self._total_preds,
                left_offset=left_offset,
                right_offset=right_offset,
            )
            current = self._total_preds[:, previous_length:, :]
        return current[0].detach().float().cpu().numpy()

    def dominant_recent(self, duration_ms: float) -> str:
        if not self._activities:
            return "unknown_speaker"
        cutoff = max(0.0, self._processed_ms - duration_ms)
        rows = [activity.probabilities for activity in self._activities if activity.end_ms >= cutoff]
        if not rows:
            return "unknown_speaker"
        mean = np.mean(np.asarray(rows, dtype=np.float32), axis=0)
        index = int(np.argmax(mean))
        if float(mean[index]) < self.settings.sortformer_activity_threshold:
            return "unknown_speaker"
        return f"speaker_{index}"

    def labels_for_recent_segments(self, duration_ms: float, segments: list[tuple[float, float]]) -> list[str]:
        utterance_start = max(0.0, self._processed_ms - duration_ms)
        labels: list[str] = []
        for start_ms, end_ms in segments:
            start = utterance_start + max(0.0, start_ms)
            end = utterance_start + min(duration_ms, end_ms)
            rows = [
                activity.probabilities
                for activity in self._activities
                if activity.end_ms > start and activity.start_ms < end
            ]
            if not rows:
                labels.append("unknown_speaker")
                continue
            mean = np.mean(np.asarray(rows, dtype=np.float32), axis=0)
            index = int(np.argmax(mean))
            labels.append(
                f"speaker_{index}"
                if float(mean[index]) >= self.settings.sortformer_activity_threshold
                else "unknown_speaker"
            )
        return labels

    async def close(self) -> None:
        if self._worker is not None:
            try:
                self._input.put_nowait(None)
            except asyncio.QueueFull:
                self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None


class TitaNetIdentifier:
    """동의 후 저장된 embedding만 읽고, 설정된 검증 threshold가 없으면 unknown을 반환한다."""

    def __init__(self, settings: CustomVoiceSettings) -> None:
        self.settings = settings
        self._model = None
        self._enrollments: dict[str, np.ndarray] = {}

    async def start(self) -> None:
        if not self.settings.speaker_embedding_dir:
            return
        await asyncio.to_thread(self._load)

    def _load(self) -> None:
        root = Path(self.settings.speaker_embedding_dir).resolve()
        if not root.is_dir():
            return
        enrollment_paths = list(root.glob("*.npy"))
        if not enrollment_paths:
            return
        import nemo.collections.asr as nemo_asr

        self._model = nemo_asr.models.EncDecSpeakerLabelModel.from_pretrained(
            model_name=self.settings.titanet_model
        ).eval()
        for path in enrollment_paths:
            embedding = np.asarray(np.load(path, allow_pickle=False), dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(embedding))
            if norm > 0:
                self._enrollments[path.stem] = embedding / norm

    async def identify(self, pcm: bytes, sample_rate: int = 16_000) -> tuple[str, float | None]:
        threshold = self.settings.speaker_similarity_threshold
        if self._model is None or not self._enrollments or threshold is None:
            return "unknown_speaker", None
        return await asyncio.to_thread(self._identify_sync, pcm, sample_rate, threshold)

    def _identify_sync(self, pcm: bytes, sample_rate: int, threshold: float) -> tuple[str, float]:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as file:
                temp_path = Path(file.name)
            with wave.open(str(temp_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(pcm)
            embedding = self._model.get_embedding(str(temp_path)).detach().float().cpu().numpy().reshape(-1)
            embedding /= max(float(np.linalg.norm(embedding)), 1e-8)
            scores = {name: float(np.dot(embedding, enrolled)) for name, enrolled in self._enrollments.items()}
            best_name = max(scores, key=scores.get)
            best_score = scores[best_name]
            return (best_name if best_score >= threshold else "unknown_speaker", best_score)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


async def create_speaker_pipeline(settings: CustomVoiceSettings) -> SpeakerPipeline:
    if settings.diarization_backend != "sortformer":
        return NullSpeakerPipeline()
    pipeline = SortformerStreamingPipeline(settings)
    try:
        await pipeline.start()
        return pipeline
    except Exception as exc:
        logger.warning("[CustomVoice] Sortformer unavailable (%s); speaker labels remain unknown", exc)
        return NullSpeakerPipeline()
