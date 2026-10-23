"""SDK 독립형 full-duplex 음성 세션 orchestration.

수신 루프는 오디오 framing/VAD만 수행하고, STT→LLM/tools→TTS는 취소 가능한 별도
task에서 실행한다. 따라서 사용자가 말하기 시작하면 진행 중인 생성과 브라우저 재생을
동시에 멈출 수 있다.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict, dataclass, replace
from enum import Enum
import json
import logging
import re
import time
from typing import Any, Optional
from uuid import uuid4

import numpy as np

from fastapi import WebSocket, WebSocketDisconnect

from .audio import AdaptiveEnergyEndpointDetector, ProsodyExtractor, ProsodyMetadata
from .silero_vad import create_vad_detector
from .config import CustomVoiceSettings
from .dialogue_control import (
    CommandIntent,
    CommandRouter,
    GateAction,
    EndpointCoordinator,
    KoreanTurnDetector,
    TurnEvidence,
    OutputGate,
    ResponseGate,
)
from .noise_engine import AudioFrame, NoiseSuppressionError
from .noise_suppression import (
    AntiAliasResampler,
    create_noise_suppressor,
)
from .privacy import PIIRedactor
from .providers import OpenAIHttpProviders, ProviderError
from .speaker_pipeline import NullSpeakerPipeline, TitaNetIdentifier, create_speaker_pipeline
from .stt_engine import create_stt_engine
from .tools import (
    ToolExecution,
    ToolExecutor,
    is_explicit_media_control_request,
    is_navigation_review_candidate,
    select_tool_schemas,
)
from .tracing import CustomTraceStore, TurnTrace
from .tts_pipeline import (
    ScheduledTextChunk,
    TTSChunkPolicy,
    TTSChunkScheduler,
    fade_out_pcm,
    stitch_pcm_boundary,
)


# Uvicorn의 handler를 사용해 별도 logging 설정 없이 서버 터미널에 바로 보이게 한다.
logger = logging.getLogger("uvicorn.error")


class SessionState(str, Enum):
    """외부 SDK가 제공하던 대화 상태를 custom runtime의 source of truth로 둔다."""

    CONNECTING = "connecting"
    LISTENING = "listening"
    USER_SPEAKING = "user_speaking"
    USER_PAUSED = "user_paused"
    WAITING_STT = "waiting_stt"
    THINKING = "thinking"
    ASSISTANT_SPEAKING = "agent_speaking"
    AGENT_SPEAKING = "agent_speaking"
    INTERRUPTING = "interrupted"
    INTERRUPTED = "interrupted"
    CLOSED = "closed"


class SentenceChunker:
    """LLM token delta를 TTS가 자연스럽게 읽을 짧은 문장으로 누적한다."""

    def __init__(
        self,
        minimum_chars: int = 32,
        maximum_chars: int = 160,
        first_chunk_min_chars: Optional[int] = None,
    ) -> None:
        self.minimum_chars = minimum_chars
        self.maximum_chars = maximum_chars
        self.first_chunk_min_chars = (
            first_chunk_min_chars if first_chunk_min_chars is not None else min(24, minimum_chars)
        )
        self._buffer = ""
        self._is_first_chunk = True

    def feed(self, delta: str) -> list[str]:
        """문장부호 또는 최대 길이에 도달한 완성 chunk만 반환한다."""

        self._buffer += delta
        chunks: list[str] = []
        while self._buffer:
            split_at = self._find_boundary()
            if split_at is None:
                break
            chunk = self._buffer[:split_at].strip()
            self._buffer = self._buffer[split_at:].lstrip()
            if chunk:
                chunks.append(chunk)
                self._is_first_chunk = False
        return chunks

    def flush(self) -> Optional[str]:
        """LLM 응답이 끝났을 때 남은 짧은 문장을 반환한다."""

        value = self._buffer.strip()
        self._buffer = ""
        self._is_first_chunk = True
        return value or None

    def _find_boundary(self) -> Optional[int]:
        """너무 짧은 합성을 피하면서 가장 이른 안전한 문장 경계를 찾는다."""

        min_len = self.first_chunk_min_chars if self._is_first_chunk else self.minimum_chars
        if len(self._buffer) >= min_len:
            for index, character in enumerate(self._buffer, start=1):
                if index >= min_len and character in ".!?。！？\n~":
                    return index
        if len(self._buffer) >= self.maximum_chars:
            space = self._buffer.rfind(" ", 0, self.maximum_chars)
            return space + 1 if space >= min_len else self.maximum_chars
        return None


@dataclass
class _TTSStreamJob:
    segment_index: int
    request: ScheduledTextChunk
    chunks: asyncio.Queue[bytes | BaseException | None]
    task: asyncio.Task[None]
    requested_at: float
    timing: dict[str, float]


class CustomVoiceRuntime:
    """WebSocket 하나에 대응하는 독립적인 cascade session."""

    def __init__(
        self,
        websocket: WebSocket,
        session_id: str,
        user_id: int,
        recipe_id: int,
        system_prompt: str,
        settings: CustomVoiceSettings,
        recipe_name: str | None = None,
        materials: str | None = None,
        recipe_metadata: dict[str, Any] | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> None:
        self.websocket = websocket
        self.settings = settings
        # NeMo import/model download는 WebSocket handshake 전에 실행하지 않는다. 요청된
        # MarbleNet이 준비될 때까지 Silero(또는 energy fallback)로 즉시 수신을 시작한다.
        initial_vad_settings = (
            replace(settings, vad_backend="silero", vad_mode="silero")
            if settings.vad_backend == "marblenet"
            else settings
        )
        self.detector = create_vad_detector(initial_vad_settings)
        self._turn_speech_segments: list[tuple[str, float, float]] = []
        self.noise_suppressor = create_noise_suppressor(
            settings.noise_suppression,
            rnnoise_library=settings.rnnoise_library,
            deepfilternet_model=settings.deepfilternet_model,
        )
        self.input_resampler = AntiAliasResampler(settings.transport_sample_rate, settings.input_sample_rate)
        self.prosody = ProsodyExtractor(settings.input_sample_rate)
        self.command_router = CommandRouter()
        self.output_gate = OutputGate()
        self.response_gate = ResponseGate(self.output_gate)
        self.redactor = PIIRedactor()
        self.providers = OpenAIHttpProviders(settings)
        self.stt_engine = create_stt_engine(settings, self.providers)
        self.speaker_pipeline = NullSpeakerPipeline()
        self.speaker_identifier = TitaNetIdentifier(settings)
        self.turn_detector = KoreanTurnDetector()
        self.endpoint_coordinator = EndpointCoordinator(settings, self.turn_detector)
        self.trace = CustomTraceStore(session_id, user_id, recipe_id, system_prompt)
        self.tools = ToolExecutor(self._send_json)
        self.recipe_name = recipe_name or ""
        self.materials = (materials or "정보 없음").strip()
        self.recipe_metadata = {
            key: (str(value).strip()[:400] if isinstance(value, str) else value)
            for key, value in (recipe_metadata or {}).items()
            if value not in (None, "", "정보 없음")
        }
        self.recipe_steps = [
            {"step": int(item.get("step", index + 1)), "text": str(item.get("text") or "")}
            for index, item in enumerate(steps or [])
        ]
        self._last_tool_summary = "없음"
        self.current_step: int | None = None
        self.step_text: str | None = None
        self.guided_step: int | None = None
        self.completed_steps: set[int] = set()
        self.pending_navigation: dict[str, Any] | None = None
        self._navigation_ack_event = asyncio.Event()
        self.active_timers: dict[str, dict[str, Any]] = {}
        self._active_turn_kind = "user_audio"
        hint_parts = ["한국어 요리 대화."]
        if recipe_name:
            hint_parts.append(f"요리: {recipe_name}.")
        if materials:
            hint_parts.append(f"재료: {materials[:120]}.")
        hint_parts.append("조리 단계 안내.")
        self.stt_prompt = " ".join(hint_parts)
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        self._send_lock = asyncio.Lock()
        self._response_task: Optional[asyncio.Task[None]] = None
        self._barge_in_task: Optional[asyncio.Task[None]] = None
        self._interruption_tasks: set[asyncio.Task[None]] = set()
        self._partial_stt_task: Optional[asyncio.Task[None]] = None
        self._live_speech_pcm: bytearray | None = None
        self._last_partial_transcript = ""
        self._partial_transcript_stable = False
        self._optional_models_task: Optional[asyncio.Task[None]] = None
        self._audio_worker_task: Optional[asyncio.Task[None]] = None
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(
            maxsize=max(10, settings.audio_receive_queue_frames)
        )
        self._dropped_audio_frames = 0
        self._speech_started_ts: Optional[float] = None
        self._pending_speech_id: Optional[str] = None
        self._barge_in_confirmed = False
        self._input_sequence = 0
        self._input_sample_index = 0
        self._audio_frames_received = 0
        self._audio_input_announced = False
        self._response_generation = 0
        self._active_response_id: str | None = None
        self._playback_response_id: str | None = None
        self._audio_pipeline_failed = False
        self._closed = False
        self._transport_closed = False
        self.state = SessionState.CONNECTING

    def _trim_messages(self, max_turns: int = 3) -> None:
        """system 프롬프트는 유지하고 최근 대화 3턴(user-assistant)을 슬라이딩 윈도우로 유지한다."""
        if len(self.messages) <= 1:
            return
        system_msg = self.messages[0]
        history = self.messages[1:]
        user_indices = [i for i, m in enumerate(history) if m.get("role") == "user"]
        if len(user_indices) > max_turns:
            cutoff = user_indices[-max_turns]
            history = history[cutoff:]
        self.messages = [system_msg] + history

    def _session_state_message(self, compact: bool = False) -> dict[str, str]:
        """전체 단계의 얇은 인덱스와 현재 진행 주변의 상세 문맥을 함께 제공한다."""
        self._expire_pending_navigation()
        step_index = min(max(self.current_step or 0, 0), max(0, len(self.recipe_steps) - 1))
        guided_step = getattr(self, "guided_step", None)
        guided_index = min(
            max(guided_step if guided_step is not None else step_index, 0),
            max(0, len(self.recipe_steps) - 1),
        )
        detail_indices = set(
            range(max(0, step_index - 1), min(len(self.recipe_steps), step_index + 2))
        )
        detail_indices.add(guided_index)
        nearby: list[str] = []
        for index in sorted(detail_indices):
            if index >= len(self.recipe_steps):
                continue
            row = self.recipe_steps[index]
            markers: list[str] = []
            if index == step_index:
                markers.append("화면")
            if index == guided_index:
                markers.append("안내")
            marker = "/".join(markers) or "주변"
            nearby.append(f"{marker} {row['step']}단계: {row['text']}")
        if not nearby and self.step_text:
            nearby.append(f"화면 {step_index + 1}단계: {self.step_text}")
        pending = getattr(self, "pending_navigation", None) or {}
        completed = ", ".join(
            f"{step}단계" for step in sorted(getattr(self, "completed_steps", set()))
        ) or "없음"
        active_timers = [
            {
                "step": timer.get("step"),
                "label": timer.get("label"),
                "remaining_seconds": max(0, round(float(timer.get("ends_at") or 0) - time.time())),
            }
            for timer in self.active_timers.values()
        ]
        state_parts = [
            "[session_state]",
            f"요리: {self.recipe_name or '정보 없음'}",
        ]
        if not compact:
            state_parts.extend(
                [
                    f"기본 메타데이터: {json.dumps(self.recipe_metadata, ensure_ascii=False) or '정보 없음'}",
                    f"재료 정보: {self.materials[:600]}",
                ]
            )
        state_parts.extend(
            [
                f"전체 단계 수: {len(self.recipe_steps)} (현재 단계 주변의 상세 정보만 제공)",
                f"현재 화면 단계: {step_index + 1}",
                f"마지막 안내 단계: {guided_index + 1}",
                f"사용자가 완료했다고 확인한 단계: {completed}",
                f"화면 이동 확인 대기: {json.dumps(pending, ensure_ascii=False) if pending else '없음'}",
                f"활성 타이머: {json.dumps(active_timers, ensure_ascii=False) if active_timers else '없음'}",
                f"현재 주변 상세:\n{' '.join(nearby) or '정보 없음'}",
                f"최근 도구 상태: {self._last_tool_summary}",
            ]
        )
        state = "\n".join(state_parts)
        return {"role": "system", "content": state}

    def _expire_pending_navigation(self, timeout_seconds: float = 5.0) -> None:
        pending = self.pending_navigation
        if not pending:
            return
        requested_at = float(pending.get("requested_at") or 0.0)
        if requested_at and time.time() - requested_at > timeout_seconds:
            target_step = pending.get("target_step")
            self.pending_navigation = None
            self._last_tool_summary = (
                f"화면 {target_step}단계 이동은 미확인, "
                f"대화 안내는 {((self.guided_step or 0) + 1)}단계"
            )

    def _sync_screen_step(
        self,
        current_step: Any,
        step_text: Any = None,
        navigation_id: Any = None,
    ) -> tuple[int | None, int]:
        """브라우저가 확정한 0-based 화면 단계를 서버 상태에 반영한다."""
        previous = self.current_step
        maximum = max(0, len(self.recipe_steps) - 1)
        try:
            confirmed = min(max(0, int(current_step)), maximum)
        except (TypeError, ValueError):
            confirmed = previous if previous is not None else 0
        self.current_step = confirmed
        if step_text is not None and str(step_text).strip():
            self.step_text = str(step_text).strip()
        elif self.recipe_steps:
            self.step_text = str(self.recipe_steps[confirmed].get("text") or "") or None
        self._expire_pending_navigation()
        pending = self.pending_navigation
        pending_id = str((pending or {}).get("navigation_id") or "")
        received_id = str(navigation_id or "")
        pending_matches = bool(pending) and int(pending.get("target_index", -1)) == confirmed
        id_matches = not received_id or not pending_id or received_id == pending_id
        if pending_matches and id_matches:
            completed_step = pending.get("completed_step")
            if pending.get("mark_current_completed") and completed_step is not None:
                self.completed_steps.add(int(completed_step))
            self.pending_navigation = None
            self.guided_step = confirmed
            self._last_tool_summary = f"화면 {confirmed + 1}단계 이동 확인"
            self._navigation_ack_event.set()
        elif pending:
            # 대기 중 목표와 다른 화면 변경은 사용자의 수동 조작으로 보고 오래된 요청을 폐기한다.
            self.pending_navigation = None
            self.guided_step = confirmed
            self._last_tool_summary = f"사용자 화면 {confirmed + 1}단계 이동 확인"
            self._navigation_ack_event.set()
        elif not pending:
            # 사용자가 직접 화면을 이동한 경우에도 다음 LLM 안내 기준을 실제 화면과 맞춘다.
            self.guided_step = confirmed
        return previous, confirmed

    @staticmethod
    def _text_ngrams(text: str, size: int = 3) -> set[str]:
        normalized = re.sub(r"[^0-9a-zA-Z가-힣]", "", text.lower())
        if len(normalized) < size:
            return {normalized} if normalized else set()
        return {normalized[index:index + size] for index in range(len(normalized) - size + 1)}

    def _update_guided_step_from_response(self, response_text: str) -> None:
        """발화가 실제로 설명한 단계를 UI와 독립적으로 보수적 추적한다."""

        text = response_text.strip()
        if not text or not self.recipe_steps:
            return
        explicit_steps = [
            int(value) for value in re.findall(r"(?<!\d)(\d{1,2})\s*(?:번\s*)?단계", text)
        ]
        valid_explicit = [step for step in explicit_steps if 1 <= step <= len(self.recipe_steps)]
        if valid_explicit:
            self.guided_step = valid_explicit[-1] - 1
            return

        response_grams = self._text_ngrams(text)
        if not response_grams:
            return
        current = self.guided_step if self.guided_step is not None else (self.current_step or 0)
        candidates: list[tuple[float, int, int]] = []
        for index, row in enumerate(self.recipe_steps):
            if abs(index - current) > 2:
                continue
            step_grams = self._text_ngrams(str(row.get("text") or ""))
            overlap = len(step_grams & response_grams)
            if not step_grams:
                continue
            candidates.append((overlap / len(step_grams), overlap, index))
        candidates.sort(reverse=True)
        if not candidates:
            return
        best_score, best_overlap, best_index = candidates[0]
        runner_score = candidates[1][0] if len(candidates) > 1 else 0.0
        required_overlap = min(4, len(self._text_ngrams(str(self.recipe_steps[best_index].get("text") or ""))))
        if (
            best_overlap >= required_overlap
            and best_score >= 0.30
            and best_score - runner_score >= 0.08
        ):
            self.guided_step = best_index

    def _llm_messages(
        self,
        *,
        tool_followup: bool = False,
        compact_state: bool = False,
    ) -> list[dict[str, Any]]:
        """고정 역할 지시, 짧은 live state, 최근 대화만 전송한다."""
        history = self.messages[1:]
        if tool_followup:
            # 첫 round가 이미 읽은 과거 대화는 두 번째 요청에서 반복하지 않는다.
            # 현재 user → assistant tool call → tool result envelope는 유지한다.
            user_indices = [
                index for index, message in enumerate(history)
                if message.get("role") == "user"
            ]
            if user_indices:
                history = history[user_indices[-1]:]
        return [
            self.messages[0],
            self._session_state_message(compact=compact_state or tool_followup),
            *history,
        ]

    @staticmethod
    def _is_detailed_request(transcript: str) -> bool:
        """Only explicit requests receive the longer voice-response budget."""
        normalized = transcript.replace(" ", "").lower()
        return any(token in normalized for token in ("자세히", "왜", "전체설명", "상세", "구체적으로"))

    @staticmethod
    def _is_instruction_request(transcript: str) -> bool:
        """조리 단계 설명에는 일반 잡담보다 충분한 출력 예산을 제공한다."""
        normalized = transcript.replace(" ", "").lower()
        return any(
            token in normalized
            for token in ("단계", "다음", "이전", "레시피", "조리", "만드는법", "어떻게해")
        )

    @staticmethod
    def _join_response_text(existing: str, addition: str) -> str:
        addition = addition.strip()
        if not addition:
            return existing
        if not existing:
            return addition
        separator = "" if existing.endswith((" ", "\n")) else " "
        return f"{existing}{separator}{addition}"

    def _compact_completed_tool_history(self) -> None:
        """도구 결과 원문과 tool-call envelope는 다음 턴에 재전송하지 않는다."""
        compacted = [self.messages[0]]
        for message in self.messages[1:]:
            if message.get("role") == "tool" or message.get("tool_calls"):
                continue
            compacted.append(message)
        self.messages = compacted

    async def run(self) -> None:
        """handshake 후 오디오/제어 메시지를 받고 종료 시 provider와 trace를 정리한다."""

        try:
            from starlette.websockets import WebSocketState
            if getattr(self.websocket, "client_state", None) != WebSocketState.CONNECTED:
                await self.websocket.accept()
        except Exception:
            pass
        logger.info(
            "[CustomVoice:%s] session started user=%s recipe=%s noise_suppression=%s "
            "transport_rate=%s vad=%s threshold=%.2f start_frames=%s",
            self.trace.session_id,
            self.trace.user_id,
            self.trace.recipe_id,
            self.settings.noise_suppression,
            self.settings.transport_sample_rate,
            type(self.detector).__name__,
            self.settings.vad_threshold,
            self.settings.speech_start_frames,
        )
        logger.info(
            "[CustomVoice:%s] endpoint mode=%s candidate_ms=%s fallback_ms=%s hard_ms=%s",
            self.trace.session_id,
            "vad+partial_semantic" if self.settings.stt_backend == "faster_whisper" else "vad+silence_fallback",
            self.settings.endpoint_candidate_silence_ms,
            self.settings.endpoint_fallback_silence_ms,
            self.settings.endpoint_hard_silence_ms,
        )
        if getattr(self.settings, "vad_debug_logging", False):
            logger.info(
                "[CustomVoice:%s] VAD debug logging enabled; only numeric acoustic diagnostics are logged",
                self.trace.session_id,
            )
        await self._send_json(
            {
                "type": "session_ready",
                "session_id": self.trace.session_id,
                "architecture": self.trace.architecture,
                "input_sample_rate": self.settings.transport_sample_rate,
                "pipeline_sample_rate": self.settings.input_sample_rate,
                "input_frame_ms": self.settings.transport_frame_ms,
                "output_sample_rate": self.settings.output_sample_rate,
                "noise_suppression": self.settings.noise_suppression,
                "vad_backend_requested": self.settings.vad_backend,
                "vad_backend_active": type(self.detector).__name__,
                "stt_backend": self.settings.stt_backend,
                "diarization_backend": self.settings.diarization_backend,
                "browser_audio_constraints": self.settings.browser_audio_constraints,
            }
        )
        await self._set_state(SessionState.LISTENING)
        self._audio_worker_task = asyncio.create_task(self._audio_worker())
        self._optional_models_task = asyncio.create_task(self._initialize_optional_models())
        try:
            while True:
                message = await self.websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    self._transport_closed = True
                    break
                if message.get("bytes") is not None:
                    self._enqueue_audio(message["bytes"])
                    continue
                if message.get("text") is not None:
                    should_close = await self._handle_control(message["text"])
                    if should_close:
                        break
        except WebSocketDisconnect:
            self._transport_closed = True
        except Exception:
            logger.exception("[CustomVoice:%s] session receive loop failed", self.trace.session_id)
            try:
                await self._send_json(
                    {
                        "type": "error",
                        "code": "session_runtime_failed",
                        "message": "Custom voice session stopped unexpectedly",
                    }
                )
            except Exception:
                pass
        finally:
            await self.close()

    async def close(self) -> None:
        """진행 중 응답을 취소하고 측정 가능한 turn과 connection을 안전하게 마감한다."""

        if self._closed:
            return
        self._closed = True
        if self._barge_in_task and not self._barge_in_task.done():
            self._barge_in_task.cancel()
        if self._partial_stt_task and not self._partial_stt_task.done():
            self._partial_stt_task.cancel()
        if self._audio_worker_task and not self._audio_worker_task.done():
            try:
                self._audio_queue.put_nowait(None)
            except asyncio.QueueFull:
                self._audio_worker_task.cancel()
        if self._optional_models_task and not self._optional_models_task.done():
            self._optional_models_task.cancel()
        if self._response_task and not self._response_task.done():
            self._response_task.cancel()
            await asyncio.gather(self._response_task, return_exceptions=True)
        pending = [
            task
            for task in (
                self._barge_in_task,
                self._partial_stt_task,
                self._audio_worker_task,
                self._optional_models_task,
            )
            if task
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._interruption_tasks:
            await asyncio.gather(*self._interruption_tasks, return_exceptions=True)
        if self.trace.active_turn is not None:
            self.trace.active_turn.response_completed_ts = time.time()
            self.trace.finish_turn()
        await self.noise_suppressor.close()
        await self.speaker_pipeline.close()
        self.trace.runtime_metrics["audio_receive_queue"] = {
            "dropped_frames": self._dropped_audio_frames,
            "capacity_frames": self._audio_queue.maxsize,
        }
        self.trace.runtime_metrics["noise_suppression"] = self.noise_suppressor.stats.summary()
        await self.providers.close()
        path = self.trace.save()
        logger.info("[CustomVoice:%s] session closed trace=%s", self.trace.session_id, path)
        self.state = SessionState.CLOSED

    def _enqueue_audio(self, pcm: bytes) -> None:
        """WebSocket 수신 루프를 VAD/NeMo/NS 추론으로부터 분리한다."""

        try:
            self._audio_queue.put_nowait(pcm)
        except asyncio.QueueFull:
            self._dropped_audio_frames += 1
            if self._dropped_audio_frames == 1 or self._dropped_audio_frames % 50 == 0:
                logger.warning(
                    "[CustomVoice:%s] audio receive queue overflow dropped=%s",
                    self.trace.session_id,
                    self._dropped_audio_frames,
                )

    async def _audio_worker(self) -> None:
        while True:
            pcm = await self._audio_queue.get()
            if pcm is None:
                return
            await self._handle_audio(pcm)

    async def _initialize_optional_models(self) -> None:
        """무거운 선택 모델 초기화가 session_ready/오디오 수신을 막지 않게 한다."""

        if self.settings.vad_backend == "marblenet":
            try:
                from .nemo_vad import MarbleNetVADDetector

                detector = await asyncio.to_thread(MarbleNetVADDetector, self.settings)
                while self.detector.talking and not self._closed:
                    await asyncio.sleep(0.05)
                if not self._closed:
                    self.detector = detector
                    logger.info("[CustomVoice:%s] MarbleNet VAD activated", self.trace.session_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[CustomVoice] MarbleNet unavailable; retaining Silero VAD: %s", exc)
        pipeline = await create_speaker_pipeline(self.settings)
        if self.settings.speaker_identification_backend == "titanet":
            try:
                await self.speaker_identifier.start()
            except Exception as exc:
                logger.warning("[CustomVoice] TitaNet unavailable; identification disabled: %s", exc)
        if self._closed:
            await pipeline.close()
            return
        self.speaker_pipeline = pipeline

    async def _handle_control(self, raw_message: str) -> bool:
        """브라우저의 text/ping/stop 제어 메시지를 처리한다."""

        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            await self._send_json({"type": "error", "message": "Invalid JSON control message"})
            return False

        message_type = message.get("type")
        if message_type == "ping":
            await self._send_json({"type": "pong"})
        elif message_type == "stop":
            return True
        elif message_type == "response_hold":
            self.response_gate.force_hold()
            await self._interrupt_active_response()
            await self._send_json({"type": "response_hold_started", "source": "control"})
            await self._set_state(SessionState.LISTENING)
        elif message_type == "response_release":
            self.response_gate.force_release()
            await self._send_json({"type": "response_hold_released", "source": "control"})
        elif message_type == "text":
            text = str(message.get("text") or message.get("message") or "").strip()
            if text:
                await self._begin_text_turn(text)
        elif message_type == "timer_complete":
            self._queue_timer_completion(message)
        elif message_type in {"resume_session", "reconnect"}:
            current_step = message.get("current_step")
            step_text = message.get("step_text")
            if current_step is not None:
                self._sync_screen_step(current_step, step_text)
            history = message.get("history") or []
            if isinstance(history, list) and history:
                for item in history[-6:]:
                    role = item.get("role")
                    content = item.get("text") or item.get("content")
                    if role in {"user", "assistant"} and content:
                        self.messages.append({"role": role, "content": str(content)})
                self._trim_messages(max_turns=3)
            if current_step is not None and int(current_step) > 0:
                step_num = int(current_step) + 1
                greeting = (
                    f"대화가 다시 연결되었어. 사용자는 지금 {step_num}단계"
                    + (f"('{step_text}')" if step_text else "")
                    + "를 진행 중이야. 초기 준비 안내를 반복하지 말고, "
                    + f"사용자를 안심시키며 {step_num}단계를 이어서 친절하게 안내해줘."
                )
                await self._begin_text_turn(greeting, internal=True)
            else:
                await self._begin_text_turn(
                    "대화를 시작해. 밝게 인사하고, 손을 씻은 뒤 준비되면 말해 달라고 짧게 안내해.",
                    internal=True,
                )
        elif message_type == "step_changed":
            if message.get("current_step") is None:
                await self._send_json({"type": "error", "message": "current_step is required"})
                return False
            previous, confirmed = self._sync_screen_step(
                message.get("current_step"),
                message.get("step_text"),
                message.get("navigation_id"),
            )
            state = self._cooking_state_snapshot()
            self.trace.add_entry(
                "step_state",
                f"화면 {confirmed + 1}단계 확인",
                {
                    "source": str(message.get("source") or "browser"),
                    "previous_screen_step": None if previous is None else previous + 1,
                    **state,
                },
            )
            logger.info(
                "[CustomVoice:%s] screen step confirmed previous=%s current=%s guided=%s pending=%s",
                self.trace.session_id,
                None if previous is None else previous + 1,
                confirmed + 1,
                state["guided_step"],
                bool(state["pending_navigation"]),
            )
        elif message_type == "generate_greeting":
            current_step = message.get("current_step")
            step_text = message.get("step_text")
            if current_step is not None:
                self._sync_screen_step(current_step, step_text)
            if current_step is not None and int(current_step) > 0:
                step_num = int(current_step) + 1
                greeting = (
                    f"대화가 다시 연결되었어. 사용자는 지금 {step_num}단계"
                    + (f"('{step_text}')" if step_text else "")
                    + "를 진행 중이야. 초기 준비 안내를 반복하지 말고, "
                    + f"사용자를 안심시키며 {step_num}단계를 이어서 친절하게 안내해줘."
                )
                await self._begin_text_turn(greeting, internal=True)
            else:
                await self._begin_text_turn(
                    "대화를 시작해. 밝게 인사하고, 손을 씻은 뒤 준비되면 말해 달라고 짧게 안내해.",
                    internal=True,
                )
        elif message_type == "playback_progress":
            played_ms = float(message.get("played_duration_ms") or 0.0)
            interrupted = bool(message.get("interrupted", False))
            if interrupted and played_ms > 0:
                self._truncate_last_assistant_speech(played_ms)
        elif message_type == "playback_finished":
            response_id = str(message.get("response_id") or "")
            if response_id and response_id == self._playback_response_id:
                self._playback_response_id = None
        elif message_type == "playback_metrics":
            response_id = str(message.get("response_id") or "")
            metrics = {
                "timestamp": time.time(),
                "response_id": response_id,
                "generation_id": int(message.get("generation_id") or 0),
                "sequence_number": int(message.get("sequence_number") or 0),
                "queued_ms": float(message.get("queued_ms") or 0.0),
                "scheduled_wait_ms": float(message.get("scheduled_wait_ms") or 0.0),
                "jitter_ms": float(message.get("jitter_ms") or 0.0),
                "target_jitter_ms": float(message.get("target_jitter_ms") or 0.0),
                "jitter_mode": str(message.get("jitter_mode") or "unknown"),
                "underruns": int(message.get("underruns") or 0),
                "browser_received_at_ms": float(message.get("browser_received_at_ms") or 0.0),
                "scheduled_playback_at_ms": float(message.get("scheduled_playback_at_ms") or 0.0),
            }
            playback = self.trace.runtime_metrics.setdefault("playback", [])
            playback.append(metrics)
        elif message_type == "capture_metrics":
            capture = {
                "timestamp": time.time(),
                "context_sample_rate": int(message.get("context_sample_rate") or 0),
                "target_sample_rate": int(message.get("target_sample_rate") or 0),
                "samples": int(message.get("samples") or 0),
                "rms": float(message.get("rms") or 0.0),
                "peak": float(message.get("peak") or 0.0),
                "track_settings": message.get("track_settings") or {},
            }
            self.trace.runtime_metrics.setdefault("browser_capture", []).append(capture)
            logger.info(
                "[CustomVoice:%s] browser capture context_rate=%s target_rate=%s samples=%s "
                "rms=%.4f peak=%.4f settings=%s",
                self.trace.session_id,
                capture["context_sample_rate"],
                capture["target_sample_rate"],
                capture["samples"],
                capture["rms"],
                capture["peak"],
                capture["track_settings"],
            )
        return False

    def _truncate_last_assistant_speech(self, played_ms: float) -> None:
        """barge-in으로 중단된 실제 오디오 청취 위치에 맞춰 assistant 메시지를 잘라낸다 (State Rollback)."""
        if not self._turn_speech_segments:
            return

        reconstructed_parts: list[str] = []
        for text, start_ms, end_ms in self._turn_speech_segments:
            if played_ms >= end_ms:
                reconstructed_parts.append(text)
            elif played_ms > start_ms:
                seg_duration = end_ms - start_ms
                if seg_duration > 0:
                    ratio = min(1.0, max(0.0, (played_ms - start_ms) / seg_duration))
                    char_count = max(1, int(round(len(text) * ratio)))
                    partial = text[:char_count].rstrip()
                    if partial:
                        reconstructed_parts.append(partial)
                break
            else:
                break

        truncated_text = "".join(reconstructed_parts).strip()
        if truncated_text:
            if not truncated_text.endswith("..."):
                truncated_text += "..."
        else:
            truncated_text = "..."

        for msg in reversed(self.messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                original = msg["content"]
                msg["content"] = truncated_text
                logger.info(
                    "[CustomVoice:%s] State Rollback: assistant speech truncated (played=%.1fms)\n  Original: %r\n  Truncated: %r",
                    self.trace.session_id,
                    played_ms,
                    original,
                    msg["content"],
                )
                break

        if self.trace.active_turn is not None:
            self.trace.active_turn.agent_response = truncated_text
            self.trace.add_entry(
                "state_rollback",
                truncated_text,
                {"played_ms": played_ms},
            )

    async def _handle_audio(self, pcm: bytes) -> None:
        """transport PCM에 optional NS/resampling을 적용한 뒤 VAD 상태를 연결한다."""

        if self._audio_pipeline_failed:
            return
        if not pcm or len(pcm) % 2:
            logger.warning(
                "[CustomVoice:%s] invalid PCM frame bytes=%s",
                self.trace.session_id,
                len(pcm),
            )
            return
        transport_frame = AudioFrame(
            pcm=pcm,
            sample_rate=self.settings.transport_sample_rate,
            sequence=self._input_sequence,
            sample_index=self._input_sample_index,
            timestamp=time.time(),
        )
        self._input_sequence += 1
        self._input_sample_index += transport_frame.samples
        try:
            suppressed = await self.noise_suppressor.process(transport_frame)
            detector_frame = self.input_resampler.process(suppressed)
        except NoiseSuppressionError as exc:
            self._audio_pipeline_failed = True
            logger.exception("[CustomVoice:%s] noise suppression failed: %s", self.trace.session_id, exc)
            await self._send_json(
                {
                    "type": "error",
                    "code": "noise_suppression_failed",
                    "message": str(exc),
                }
            )
            return

        if self._live_speech_pcm is not None:
            self._live_speech_pcm.extend(detector_frame.pcm)
        detector_events = self.detector.push(detector_frame.pcm)
        self.speaker_pipeline.submit(detector_frame.pcm)
        self._audio_frames_received += 1
        if self._audio_frames_received == 1 or self._audio_frames_received % 50 == 0:
            samples = np.frombuffer(detector_frame.pcm, dtype="<i2").astype(np.float32)
            rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
            peak = int(np.max(np.abs(samples))) if samples.size else 0
            speech_probability = getattr(self.detector, "last_probability", None)
            logger.info(
                "[CustomVoice:%s] audio input frames=%s bytes=%s rms=%.0f peak=%s vad_prob=%s talking=%s",
                self.trace.session_id,
                self._audio_frames_received,
                len(pcm),
                rms,
                peak,
                f"{speech_probability:.3f}" if speech_probability is not None else "n/a",
                self.detector.talking,
            )
            drain_diagnostics = getattr(self.detector, "drain_diagnostics", None)
            if callable(drain_diagnostics):
                diagnostic = drain_diagnostics()
                logger.info(
                    "[CustomVoice:%s] VAD window frames=%s max_prob=%.3f above_threshold=%s "
                    "longest_run=%s required_run=%s threshold=%.2f",
                    self.trace.session_id,
                    diagnostic["frames"],
                    diagnostic["max_probability"],
                    diagnostic["above_threshold"],
                    diagnostic["longest_voiced_run"],
                    diagnostic["required_start_frames"],
                    diagnostic["start_threshold"],
                )
            if not self._audio_input_announced:
                self._audio_input_announced = True
                await self._send_json(
                    {
                        "type": "audio_input_ready",
                        "sample_rate": detector_frame.sample_rate,
                        "frame_bytes": len(pcm),
                    }
                )

        for event in detector_events:
            if event.kind == "speech_start":
                self._speech_started_ts = time.time()
                self._barge_in_confirmed = False
                logger.info("[CustomVoice:%s] speech started", self.trace.session_id)
                # VAD start만으로는 스피커 잔향·클릭도 들어올 수 있다. 재생은 멈추지 않고
                # 아주 짧게 추가 음성 확률을 확인한 뒤에만 barge-in을 확정한다.
                response_active = self._response_task and not self._response_task.done()
                playback_active = self._playback_response_id is not None
                if response_active or playback_active:
                    if self._barge_in_task and not self._barge_in_task.done():
                        self._barge_in_task.cancel()
                    self._barge_in_task = asyncio.create_task(self._confirm_barge_in())
                speech_id = uuid4().hex
                self._pending_speech_id = speech_id
                # Detector가 speech-start 판단 전에 보존한 pre-roll까지 STT 입력에 포함한다.
                # 현재 transport frame만 사용하면 발화 첫 음절이 잘릴 수 있다.
                initial_utterance = getattr(self.detector, "current_utterance", b"")
                self._live_speech_pcm = bytearray(initial_utterance or event.utterance or detector_frame.pcm)
                self._last_partial_transcript = ""
                self._partial_transcript_stable = False
                self.endpoint_coordinator.reset()
                if self.settings.stt_backend == "faster_whisper":
                    self._partial_stt_task = asyncio.create_task(self._partial_stt_loop(speech_id))
                if not (self._response_task and not self._response_task.done()):
                    self.trace.start_turn(speech_id=speech_id, speech_started_ts=self._speech_started_ts)
                await self._set_state(SessionState.USER_SPEAKING)
                await self._send_json({"type": "user_speech_started", "speech_id": speech_id})
            elif event.kind == "turn_end" and event.utterance:
                # Detector 자체 종료는 semantic endpoint가 실패한 경우의 최종 안전망이다.
                await self._finish_live_speech(event.utterance, event.duration_ms, "vad_hard_timeout")

        if self._live_speech_pcm is not None and self.detector.talking:
            decision = self.endpoint_coordinator.decide(
                TurnEvidence(
                    speech_duration_ms=float(getattr(self.detector, "speech_duration_ms", 0.0)),
                    silence_duration_ms=float(getattr(self.detector, "silence_duration_ms", 0.0)),
                    transcript=self._last_partial_transcript,
                    partial_stable=self._partial_transcript_stable,
                    assistant_speaking=bool(self._playback_response_id),
                    speech_probability=getattr(self.detector, "last_probability", None),
                    session_state=self.state.value,
                )
            )
            if decision.end_turn:
                pcm = bytes(self._live_speech_pcm)
                duration_ms = len(pcm) / 2 / self.settings.input_sample_rate * 1000.0
                await self._finish_live_speech(pcm, duration_ms, decision.reason or "endpoint")

    async def _finish_live_speech(self, pcm: bytes, duration_ms: float, reason: str) -> None:
        """Endpoint 결정 뒤 STT 경로를 한 번만 시작한다."""
        if self._live_speech_pcm is None:
            return
        endpoint_completed_ts = time.time()
        observed_silence_ms = max(0.0, float(getattr(self.detector, "silence_duration_ms", 0.0)))
        self._live_speech_pcm = None
        self.detector.reset()
        self.endpoint_coordinator.reset()
        if self._partial_stt_task and not self._partial_stt_task.done():
            self._partial_stt_task.cancel()
        trace = self.trace.active_turn
        if trace is None or trace.speech_id != self._pending_speech_id:
            trace = self.trace.start_turn(self._pending_speech_id or uuid4().hex, self._speech_started_ts)
        self._pending_speech_id = None
        trace.last_voice_ts = endpoint_completed_ts - observed_silence_ms / 1000.0
        trace.endpoint_completed_ts = endpoint_completed_ts
        trace.user_speech_end_ts = endpoint_completed_ts
        trace.user_audio_duration_ms = duration_ms
        logger.info(
            "[CustomVoice:%s] speech ended turn=%s duration_ms=%.1f endpoint=%s",
            self.trace.session_id, trace.turn_id, duration_ms, reason,
        )
        await self._set_state(SessionState.WAITING_STT)
        await self._send_json({"type": "user_speech_ended", "speech_id": trace.speech_id, "endpoint": reason})
        self._response_task = asyncio.create_task(self._process_audio_turn(pcm, trace))

    async def _partial_stt_loop(self, speech_id: str) -> None:
        """로컬 STT만 rolling snapshot을 재추론하며 partial은 명령 실행에 사용하지 않는다."""

        interval = max(250, self.settings.partial_stt_interval_ms) / 1000.0
        minimum_bytes = int(16_000 * 2 * self.settings.partial_stt_min_audio_ms / 1000)
        try:
            while self._live_speech_pcm is not None:
                await asyncio.sleep(interval)
                buffer = self._live_speech_pcm
                if buffer is None or len(buffer) < minimum_bytes:
                    continue
                result = await self.stt_engine.transcribe(
                    bytes(buffer),
                    prompt=self.stt_prompt,
                    partial=True,
                )
                transcript = self.redactor.redact(result.text).strip()
                if not transcript:
                    continue
                stable = transcript == self._last_partial_transcript
                self._last_partial_transcript = transcript
                self._partial_transcript_stable = stable
                self.endpoint_coordinator.update_partial(transcript, stable=stable)
                if stable:
                    continue
                await self._send_json(
                    {
                        "type": "user_transcript",
                        "speech_id": speech_id,
                        "text": transcript,
                        "final": False,
                        "mutable": True,
                    }
                )
                if self.turn_detector.is_explicit_interrupt(transcript):
                    if self._response_task and not self._response_task.done():
                        self._barge_in_confirmed = True
                        await self._interrupt_active_response()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("[CustomVoice:%s] partial STT disabled for turn: %s", self.trace.session_id, exc)

    async def _confirm_barge_in(self) -> None:
        """VAD 시작 뒤에도 실제 음성 확률이 유지될 때만 재생을 취소한다."""
        try:
            await asyncio.sleep(max(0, self.settings.barge_in_confirmation_ms) / 1000.0)
            probability = getattr(self.detector, "last_probability", None)
            # Silero가 없는 backend는 talking 상태만 사용한다. Silero일 때는 시작 threshold를
            # 다시 만족해야 하므로, 짧은 잔향/저에너지 노이즈가 playback_stop을 만들지 않는다.
            confirmed = self.detector.talking and (
                probability is None or probability >= self.settings.vad_threshold
            )
            response_active = self._response_task and not self._response_task.done()
            playback_active = self._playback_response_id is not None
            if confirmed and (response_active or playback_active):
                self._barge_in_confirmed = True
                await self._set_state(SessionState.INTERRUPTING)
                await self._interrupt_active_response()
        except asyncio.CancelledError:
            return

    def _queue_timer_completion(self, message: dict[str, Any]) -> None:
        """브라우저 타이머 완료를 검증하고 진행 중 응답 뒤에 내부 알림으로 예약한다."""

        timer_id = str(message.get("timer_id") or "")
        timer = self.active_timers.pop(timer_id, None) if timer_id else None
        if timer is None:
            self.trace.add_entry(
                "timer_event_rejected",
                "unknown timer completion",
                {"timer_id": timer_id or None},
            )
            return
        label = str(timer.get("label") or f"{timer.get('step')}단계 타이머")
        duration = int(timer.get("duration") or 0)
        self._last_tool_summary = f"{label} {duration}초 완료"
        self.trace.add_entry(
            "timer_complete",
            label,
            {"timer_id": timer_id, "step": timer.get("step"), "duration": duration},
        )

        async def deliver() -> None:
            while True:
                active = self._response_task
                if not active or active.done():
                    break
                await asyncio.gather(active, return_exceptions=True)
            if self._closed:
                return
            prompt = (
                f"[internal_event type=timer_complete timer_id={timer_id}] "
                f"'{label}' {duration}초 타이머가 끝났다. 사용자 발화로 취급하거나 도구를 호출하지 말고, "
                "완료 사실을 자연스러운 한국어 한 문장으로 알려줘. 레시피 단계를 자동으로 이동하지 마."
            )
            await self._begin_text_turn(
                prompt,
                internal=True,
                turn_type="timer_complete",
                interrupt_active=False,
            )

        task = asyncio.create_task(deliver())
        self._interruption_tasks.add(task)
        task.add_done_callback(self._interruption_tasks.discard)

    async def _begin_text_turn(
        self,
        text: str,
        internal: bool = False,
        turn_type: str | None = None,
        interrupt_active: bool = True,
    ) -> None:
        """타이머/초기 인사 같은 text 입력도 동일한 LLM→TTS 파이프라인에 태운다."""

        if interrupt_active:
            await self._interrupt_active_response()
        now = time.time()
        trace = self.trace.start_turn(
            uuid4().hex,
            now,
            turn_type=turn_type or ("system_internal" if internal else "user_text"),
        )
        trace.last_voice_ts = now
        trace.endpoint_completed_ts = now
        trace.user_speech_end_ts = now
        trace.stt_completed_ts = now
        trace.user_transcript = text
        if not internal:
            self.trace.add_entry("user", self.redactor.redact(text), {"input": "text"})
            if not await self._authorize_response(self.redactor.redact(text), trace):
                await self._set_state(SessionState.LISTENING)
                return
        await self._set_state(SessionState.THINKING)
        output_token = self.output_gate.issue_token()
        self._response_task = asyncio.create_task(
            self._respond(
                self.redactor.redact(text),
                ProsodyMetadata(None, 0.0, "normal", "neutral", 0.0),
                trace,
                output_token,
            )
        )

    async def _authorize_response(self, transcript: str, trace: TurnTrace) -> bool:
        """문맥 기반 sLLM Command Router와 stateful gate를 통과한 turn만 생성 단계로 보낸다."""

        normalized = transcript.replace(" ", "").lower()
        # 정상 모드의 명시적 영상 제어는 ``멈춰``라는 단어가 있더라도 응답 보류 명령이 아니다.
        # 실제 도구 선택과 인자 검증은 뒤의 main LLM/ToolExecutor가 계속 담당한다.
        if not self.response_gate.is_holding and is_explicit_media_control_request(transcript):
            self.trace.add_entry(
                "response_gate",
                "allow",
                {
                    "intent": "conversation",
                    "confidence": 1.0,
                    "reason": "explicit_ui_control_precedence",
                },
            )
            return True
        gate_cue = any(
            cue in normalized
            for cue in ("답하지", "대답하지", "말하지", "멈춰", "그만", "재개", "계속", "다시대답", "다시말해도")
        )
        if not self.response_gate.is_holding and not gate_cue:
            self.trace.add_entry(
                "response_gate",
                "allow",
                {"intent": "conversation", "confidence": 1.0, "reason": "no_response_control_cue"},
            )
            logger.info(
                "[CustomVoice:%s] response gate turn=%s source=local_safety_filter action=allow",
                self.trace.session_id,
                trace.turn_id,
            )
            return True

        # 현재 발화를 넣기 전의 최근 대화와 HOLD 상태를 router에 함께 전달한다.
        recent_turns: list[dict[str, str]] = []
        for msg in self.messages[-6:]:
            role = msg.get("role")
            content = msg.get("content")
            if role in {"user", "assistant"} and content and isinstance(content, str):
                recent_turns.append({"role": role, "content": content[:300]})

        context = {
            "session_mode": self.response_gate.mode.value,
            "release_confirmation_pending": self.response_gate.release_confirmation_pending,
            "recipe_name": self.recipe_name,
            "current_step": self.step_text
            or (f"{self.current_step + 1}단계" if self.current_step is not None else "조리 진행 중"),
            "recent_dialogue": recent_turns,
        }

        router_requested_at = time.time()
        route = await self.command_router.route(
            transcript,
            context=context,
            classifier=self.providers,
        )
        router_elapsed_ms = (time.time() - router_requested_at) * 1000.0
        action = self.response_gate.decide(route)
        logger.info(
            "[CustomVoice:%s] response gate turn=%s intent=%s confidence=%.2f action=%s router_ms=%.1f mode=%s",
            self.trace.session_id,
            trace.turn_id,
            route.intent.value,
            route.confidence,
            action.value,
            router_elapsed_ms,
            self.response_gate.mode.value,
        )
        self.trace.add_entry(
            "response_gate",
            action.value,
            {
                "intent": route.intent.value,
                "confidence": route.confidence,
                "reason": route.reason,
            },
        )
        if action is GateAction.ALLOW:
            return True

        trace.response_completed_ts = time.time()
        self.trace.finish_turn()
        if action is GateAction.ENTER_HOLD:
            await self._send_json({"type": "response_hold_started", "source": "voice"})
        elif action is GateAction.REQUIRE_RELEASE_CONFIRMATION:
            await self._send_json(
                {
                    "type": "release_confirmation_required",
                    "message": "응답을 다시 시작하려는 게 맞으면 한 번 더 확인해줘.",
                }
            )
        elif action is GateAction.EXIT_HOLD:
            await self._send_json({"type": "response_hold_released", "source": "voice"})
        else:
            # GateAction.DROP
            if route.intent is CommandIntent.NOISE:
                await self._send_json({"type": "response_suppressed", "reason": "noise"})
            elif route.intent is CommandIntent.SIDE_TALK:
                await self._send_json({"type": "response_suppressed", "reason": "side_talk"})
            else:
                await self._send_json({"type": "response_suppressed", "reason": "response_hold"})
        return False

    async def _interrupt_active_response(self) -> None:
        """barge-in 시 서버 생성 task와 클라이언트에 예약된 오디오를 함께 중단한다."""

        # 브라우저에 대기 중이거나 재생 중인 오디오를 즉시 멈추도록 항상 playback_stop을 우선 전송한다.
        self._response_generation += 1
        invalidated_response_id = self._active_response_id
        self._active_response_id = None
        self._playback_response_id = None
        await self._send_json(
            {
                "type": "playback_stop",
                "response_id": invalidated_response_id,
                "generation_id": self._response_generation,
            }
        )

        task = self._response_task
        if not task or task.done():
            return
        interrupted_at = time.time()
        previous = self.trace.active_turn
        if previous is not None:
            previous.interruption_ts = interrupted_at
        await self._set_state(SessionState.INTERRUPTED)
        task.cancel()

        async def finalize() -> None:
            await asyncio.gather(task, return_exceptions=True)
            stopped_at = time.time()
            if previous is not None:
                previous.interruption_stopped_ts = stopped_at
                previous.response_completed_ts = stopped_at
                self.trace.finish_turn(previous)
                logger.info(
                    "[CustomVoice:%s] response interrupted turn=%s stop_ms=%.1f",
                    self.trace.session_id,
                    previous.turn_id,
                    (stopped_at - interrupted_at) * 1000.0,
                )

        finalize_task = asyncio.create_task(finalize())
        self._interruption_tasks.add(finalize_task)
        finalize_task.add_done_callback(self._interruption_tasks.discard)
        self._response_task = None
        return

    async def _process_audio_turn(self, pcm: bytes, trace: TurnTrace) -> None:
        """prosody gate를 먼저 검사하고 STT·PII 필터를 거쳐 응답 pipeline으로 넘긴다."""

        try:
            # 아주 낮은 에너지의 입력은 STT prompt hallucination과 불필요한 API 호출을
            # 만들므로 로컬 prosody gate를 먼저 통과시킨다. 계산 비용은 수 ms 수준이다.
            prosody = await asyncio.to_thread(self.prosody.extract, pcm)
            trace.prosody = asdict(prosody)
            if prosody.rms_energy < self.settings.minimum_utterance_rms:
                trace.response_completed_ts = time.time()
                self.trace.add_entry(
                    "vad_rejected",
                    "low_energy_utterance",
                    {"rms_energy": prosody.rms_energy, "minimum": self.settings.minimum_utterance_rms},
                )
                self.trace.finish_turn()
                logger.info(
                    "[CustomVoice:%s] low-energy utterance rejected turn=%s rms=%.4f minimum=%.4f",
                    self.trace.session_id,
                    trace.turn_id,
                    prosody.rms_energy,
                    self.settings.minimum_utterance_rms,
                )
                await self._send_json({"type": "empty_transcript", "reason": "low_energy"})
                await self._set_state(SessionState.LISTENING)
                return

            logger.info("[CustomVoice:%s] STT request turn=%s", self.trace.session_id, trace.turn_id)
            stt_requested_at = time.time()
            stt_result = await self.stt_engine.transcribe(pcm, prompt=self.stt_prompt)
            trace.stt_completed_ts = time.time()
            sanitized = self.redactor.redact(stt_result.text)
            trace.user_transcript = sanitized
            if not sanitized:
                trace.response_completed_ts = time.time()
                self.trace.finish_turn()
                await self._send_json({"type": "empty_transcript"})
                await self._set_state(SessionState.LISTENING)
                return
            logger.info(
                "[CustomVoice:%s] STT completed turn=%s elapsed_ms=%.1f text=%r",
                self.trace.session_id,
                trace.turn_id,
                (trace.stt_completed_ts - stt_requested_at) * 1000.0,
                sanitized[:100],
            )
            utterance_ms = len(pcm) / 2 / 16_000 * 1000.0
            speaker = self.speaker_pipeline.dominant_recent(utterance_ms)
            segment_speakers = self.speaker_pipeline.labels_for_recent_segments(
                utterance_ms,
                [(segment.start_ms, segment.end_ms) for segment in stt_result.segments],
            )
            identity, identity_score = await self.speaker_identifier.identify(pcm)
            segment_payload = [
                {
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "text": self.redactor.redact(segment.text),
                    "speaker": segment_speakers[index],
                    "avg_logprob": segment.avg_logprob,
                    "no_speech_prob": segment.no_speech_prob,
                }
                for index, segment in enumerate(stt_result.segments)
            ]
            self.trace.add_entry(
                "user",
                sanitized,
                {
                    "prosody": asdict(prosody),
                    "speaker": speaker,
                    "speaker_identity": identity,
                    "speaker_identity_score": identity_score,
                    "segments": segment_payload,
                },
            )
            await self._send_json(
                {
                    "type": "user_transcript",
                    "speech_id": trace.speech_id,
                    "text": sanitized,
                    "final": True,
                    "speaker": speaker,
                    "speaker_identity": identity,
                    "speaker_identity_score": identity_score,
                    "segments": segment_payload,
                }
            )
            if self.turn_detector.is_backchannel(sanitized) and self._barge_in_confirmed:
                trace.response_completed_ts = time.time()
                self.trace.finish_turn()
                await self._set_state(SessionState.LISTENING)
                return
            await self._set_state(SessionState.THINKING)
            if not await self._authorize_response(sanitized, trace):
                await self._set_state(SessionState.LISTENING)
                return
            await self._respond(sanitized, prosody, trace, self.output_gate.issue_token())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_turn(trace, exc)

    async def _respond(
        self,
        transcript: str,
        prosody: ProsodyMetadata,
        trace: TurnTrace,
        output_token: int | None = None,
    ) -> None:
        """LLM token을 UI와 sentence TTS queue로 fan-out하고 최종 trace를 확정한다."""

        token = self.output_gate.issue_token() if output_token is None else output_token
        if not self.output_gate.allows(token):
            return
        self._response_generation += 1
        generation_id = self._response_generation
        response_id = uuid4().hex
        self._active_response_id = response_id
        tts_queue: asyncio.Queue[Optional[ScheduledTextChunk]] = asyncio.Queue()
        tts_task = asyncio.create_task(
            self._tts_worker(tts_queue, trace, token, response_id, generation_id)
        )
        chunker = TTSChunkScheduler(
            TTSChunkPolicy(
                preferred_min_chars=self.settings.tts_preferred_min_chars,
                target_chars=self.settings.tts_target_chars,
                maximum_chars=self.settings.tts_maximum_chars,
                maximum_latency_ms=self.settings.tts_maximum_chunk_latency_ms,
                first_min_chars=self.settings.tts_first_min_chars,
                first_maximum_latency_ms=self.settings.tts_first_chunk_latency_ms,
            )
        )
        response_text = ""
        self._turn_speech_segments = []
        navigation_review_task = self._start_navigation_review(transcript)
        try:
            await self._send_json(
                {
                    "type": "response_started",
                    "response_id": response_id,
                    "generation_id": generation_id,
                }
            )
            # prosody는 별도 system 지시가 아닌 해당 user turn의 제한된 문맥으로만 주입한다.
            self.messages.append({"role": "user", "content": f"{prosody.prompt_hint()}\n{transcript}"})
            self._active_transcript = transcript
            self._active_response_max_tokens = (
                self.settings.llm_detailed_max_tokens
                if self._is_detailed_request(transcript)
                else (
                    self.settings.llm_instruction_max_tokens
                    if self._is_instruction_request(transcript)
                    else self.settings.llm_default_max_tokens
                )
            )
            for _tool_round in range(3):
                content, tool_calls, usage = await self._stream_one_llm_round(
                    trace,
                    chunker,
                    tts_queue,
                    token,
                    response_id,
                    generation_id,
                )
                response_text = self._join_response_text(response_text, content)
                trace.input_tokens += int(usage.get("prompt_tokens", 0) or 0)
                trace.output_tokens += int(usage.get("completion_tokens", 0) or 0)
                if not tool_calls:
                    self.messages.append({"role": "assistant", "content": content})
                    break

                # 모델이 직접 만든 선행 발화만 보존한다. 도구별 고정 확인 멘트는 실제
                # 사용자 의도나 실행 결과와 어긋날 수 있어 생성하지 않는다.
                ack_text = content.strip()

                # assistant tool-call message와 각 tool 결과를 OpenAI 호환 history 형태로 보존
                self.messages.append({"role": "assistant", "content": ack_text or None, "tool_calls": tool_calls})

                # 2단계 디스패처: 백그라운드 I/O 실행과 선행 음성 안내 TTS를 분리/동시 진행
                await self._execute_tools(
                    tool_calls,
                    trace,
                    transcript=transcript,
                    navigation_review_task=navigation_review_task,
                )

            self._compact_completed_tool_history()
            self._trim_messages(max_turns=3)
            tail = chunker.flush()
            if tail:
                await tts_queue.put(tail)
            await tts_queue.put(None)
            await tts_task
            trace.agent_response = response_text.strip()
            guided_before_response = self.guided_step
            self._update_guided_step_from_response(trace.agent_response)
            trace.response_completed_ts = time.time()
            assistant_metadata: dict[str, Any] = {
                "is_final": True,
                "state_after": self._cooking_state_snapshot(),
            }
            if self.guided_step != guided_before_response:
                assistant_metadata["guided_step_source"] = "assistant_recipe_match"
            self.trace.add_entry("assistant", trace.agent_response or "", assistant_metadata)
            self.trace.finish_turn()
            if self.output_gate.allows(token):
                await self._send_json(
                    {
                        "type": "assistant_done",
                        "text": trace.agent_response or "",
                        "response_id": response_id,
                        "generation_id": generation_id,
                    }
                )
            if self._active_response_id == response_id:
                self._active_response_id = None
            await self._cancel_navigation_review(navigation_review_task)
            await self._set_state(SessionState.LISTENING)
        except asyncio.CancelledError:
            await self._cancel_navigation_review(navigation_review_task)
            tts_task.cancel()
            await asyncio.gather(tts_task, return_exceptions=True)
            if response_text.strip():
                self.messages.append({"role": "assistant", "content": response_text.strip()})
            raise
        except Exception as exc:
            await self._cancel_navigation_review(navigation_review_task)
            tts_task.cancel()
            await asyncio.gather(tts_task, return_exceptions=True)
            await self._fail_turn(trace, exc)

    async def _stream_one_llm_round(
        self,
        trace: TurnTrace,
        chunker: TTSChunkScheduler,
        tts_queue: asyncio.Queue[Optional[ScheduledTextChunk]],
        output_token: int,
        response_id: str,
        generation_id: int,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        """LLM SSE 한 회차에서 text, function arguments, usage를 동시에 조립한다."""

        content_parts: list[str] = []
        tool_parts: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        tool_followup = trace.llm_rounds > 0
        compact_internal = trace.turn_type in {"system_internal", "timer_complete"}
        llm_messages = self._llm_messages(
            tool_followup=tool_followup,
            compact_state=compact_internal,
        )
        selected_tools = (
            select_tool_schemas(getattr(self, "_active_transcript", ""))
            if trace.turn_type in {"user_audio", "user_text"}
            else []
        )
        trace.llm_rounds += 1
        if trace.llm_requested_ts is None:
            trace.llm_requested_ts = time.time()
        # 운영 분석에서는 실제 API로 전달한 system/state/history/tool schema 전체를
        # 한 항목으로 확인할 수 있어야 한다. 모든 user text는 앞 단계에서 PII redaction을 거친다.
        self.trace.add_entry(
            "llm_request",
            json.dumps(
                {
                    "model": self.settings.llm_model,
                    "max_tokens": getattr(self, "_active_response_max_tokens", self.settings.llm_default_max_tokens),
                    "context_profile": (
                        "tool_followup" if tool_followup
                        else "compact_internal" if compact_internal
                        else "full"
                    ),
                    "messages": llm_messages,
                    "tools": selected_tools,
                },
                ensure_ascii=False,
            ),
            {"turn_id": trace.turn_id, "message_count": len(llm_messages)},
        )
        stream = self.providers.stream_chat(
            llm_messages,
            selected_tools,
            max_tokens=getattr(self, "_active_response_max_tokens", self.settings.llm_default_max_tokens),
        ).__aiter__()
        pending_event: asyncio.Task[Any] | None = asyncio.create_task(anext(stream))
        try:
            while pending_event is not None:
                deadline = chunker.seconds_until_deadline()
                done, _ = await asyncio.wait(
                    {pending_event},
                    timeout=deadline,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    due = chunker.flush_due()
                    if due:
                        await tts_queue.put(due)
                    continue
                try:
                    event = pending_event.result()
                except StopAsyncIteration:
                    pending_event = None
                    break
                pending_event = asyncio.create_task(anext(stream))
                if not self.output_gate.allows(output_token):
                    raise asyncio.CancelledError
                if event.get("usage"):
                    usage = event["usage"]
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    if trace.first_token_ts is None:
                        trace.first_token_ts = time.time()
                        logger.info("[CustomVoice:%s] LLM first token turn=%s", self.trace.session_id, trace.turn_id)
                    content_parts.append(content)
                    await self._send_json(
                        {
                            "type": "assistant_delta",
                            "text": content,
                            "response_id": response_id,
                            "generation_id": generation_id,
                        }
                    )
                    for scheduled_chunk in chunker.feed(content):
                        await tts_queue.put(scheduled_chunk)
                for call_delta in delta.get("tool_calls") or []:
                    index = int(call_delta.get("index", 0))
                    part = tool_parts.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    part["id"] += call_delta.get("id") or ""
                    function = call_delta.get("function") or {}
                    part["function"]["name"] += function.get("name") or ""
                    part["function"]["arguments"] += function.get("arguments") or ""
        finally:
            if pending_event is not None and not pending_event.done():
                pending_event.cancel()
                await asyncio.gather(pending_event, return_exceptions=True)
        return "".join(content_parts), [tool_parts[key] for key in sorted(tool_parts)], usage

    def _cooking_state_snapshot(self) -> dict[str, Any]:
        """도구 제안·실행·UI 확인 시점의 진행 상태를 같은 형식으로 기록한다."""
        current = getattr(self, "current_step", None)
        guided = getattr(self, "guided_step", None)
        return {
            "screen_step": None if current is None else current + 1,
            "guided_step": None if guided is None else guided + 1,
            "completed_steps": sorted(getattr(self, "completed_steps", set())),
            "pending_navigation": getattr(self, "pending_navigation", None),
        }

    def _start_navigation_review(
        self,
        transcript: str,
    ) -> asyncio.Task[dict[str, Any]] | None:
        """단계 관련 발화만 main LLM과 동시에 검토한다."""

        if not is_navigation_review_candidate(transcript):
            return None
        self.trace.add_entry(
            "navigation_review_started",
            transcript,
            {"source": "parallel_preflight"},
        )
        return asyncio.create_task(
            self._review_navigation_call(transcript, {}),
            name=f"navigation-review-{self.trace.session_id}",
        )

    @staticmethod
    async def _cancel_navigation_review(
        task: asyncio.Task[dict[str, Any]] | None,
    ) -> None:
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _parallel_navigation_review(
        self,
        transcript: str,
        proposed_arguments: dict[str, Any],
        task: asyncio.Task[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """main LLM과 겹쳐 실행된 reviewer를 짧게 합류하고 제안과 일치시키는 경계다."""

        local_review = self._explicit_navigation_review(transcript, proposed_arguments)
        if local_review is not None:
            await self._cancel_navigation_review(task)
            local_review["critical_wait_ms"] = 0.0
            return local_review

        wait_started = time.perf_counter()
        if task is None:
            # 문자열 기반 preflight 선별은 비용 최적화일 뿐 승인 경계가 아니다. 메인 LLM이
            # 실제 단계 이동을 제안했다면 "다 썰었어" 같은 자유로운 완료 표현도 의미 기반으로 검증한다.
            self.trace.add_entry(
                "navigation_review_started",
                transcript,
                {"source": "on_demand", "proposed_arguments": proposed_arguments},
            )
            review = await self._review_navigation_call(transcript, proposed_arguments)
            critical_wait_ms = (time.perf_counter() - wait_started) * 1000.0
            review["critical_wait_ms"] = round(critical_wait_ms, 1)
            review["review_source"] = "on_demand"
        else:
            join_timeout = max(0, self.settings.navigation_review_join_timeout_ms) / 1000.0
            try:
                review = await asyncio.wait_for(asyncio.shield(task), timeout=join_timeout)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                critical_wait_ms = (time.perf_counter() - wait_started) * 1000.0
                return {
                    "decision": "clarify",
                    "action": None,
                    "target_step": None,
                    "mark_current_completed": False,
                    "reason": "parallel navigation reviewer did not finish in time",
                    "latency_ms": round(critical_wait_ms, 1),
                    "critical_wait_ms": round(critical_wait_ms, 1),
                    "review_source": "parallel_timeout",
                }

            critical_wait_ms = (time.perf_counter() - wait_started) * 1000.0
            review["critical_wait_ms"] = round(critical_wait_ms, 1)
            review["review_source"] = "parallel_preflight"

        proposed_action = str(proposed_arguments.get("action") or "")
        reviewed_action = str(review.get("action") or "")
        actions_match = proposed_action == reviewed_action
        if proposed_action == "set" and actions_match:
            try:
                actions_match = int(proposed_arguments.get("target_step")) == int(
                    review.get("target_step")
                )
            except (TypeError, ValueError):
                actions_match = False
        if review.get("decision") == "allow" and not actions_match:
            return {
                **review,
                "decision": "clarify",
                "action": None,
                "target_step": None,
                "mark_current_completed": False,
                "reason": "main LLM proposal and navigation reviewer disagreed",
            }
        return review

    async def _review_navigation_call(
        self,
        transcript: str,
        proposed_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """작은 모델이 실제 사용자 발화와 상태를 기준으로 이동 제안을 승인한다."""
        recent_dialogue = [
            {"role": msg.get("role"), "content": str(msg.get("content") or "")[:240]}
            for msg in self.messages[-5:]
            if msg.get("role") in {"user", "assistant"} and msg.get("content")
        ]
        screen_index = min(
            max(self.current_step or 0, 0),
            max(0, len(self.recipe_steps) - 1),
        )
        guided_index = min(
            max(self.guided_step if self.guided_step is not None else screen_index, 0),
            max(0, len(self.recipe_steps) - 1),
        )
        nearby_indices: set[int] = set()
        for center in (screen_index, guided_index):
            nearby_indices.update(
                range(max(0, center - 1), min(len(self.recipe_steps), center + 2))
            )
        nearby_steps = [self.recipe_steps[index] for index in sorted(nearby_indices)]
        context = {
            **self._cooking_state_snapshot(),
            "recipe_name": self.recipe_name,
            "step_outline": [
                {"step": row["step"], "text": str(row.get("text") or "")[:80]}
                for row in nearby_steps
            ],
            "recent_dialogue": recent_dialogue,
        }
        started = time.perf_counter()
        try:
            review = await self.providers.review_navigation(
                transcript,
                proposed_arguments,
                context,
            )
        except Exception as exc:
            logger.warning(
                "[CustomVoice:%s] navigation review failed; side effect blocked: %s",
                self.trace.session_id,
                exc,
            )
            review = {
                "decision": "clarify",
                "action": None,
                "target_step": None,
                "mark_current_completed": False,
                "reason": "navigation reviewer unavailable",
                "review_error": f"{type(exc).__name__}: {str(exc)[:240]}",
            }
        review["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        return review

    @staticmethod
    def _explicit_navigation_review(
        transcript: str,
        proposed_arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        """명시적인 화면 이동 요청만 지연 없는 로컬 검증으로 승인한다.

        이 검사는 답변을 만들거나 명령을 추론하지 않는다. 메인 LLM이 제안한 side effect가
        현재 발화에 실제로 적혀 있는지만 보수적으로 확인하며, 나머지는 reviewer로 보낸다.
        """

        action = str(proposed_arguments.get("action") or "")
        normalized = re.sub(r"[\s.!?~。！？,]", "", transcript.lower())
        request_cue = any(
            cue in normalized
            for cue in ("알려", "보여", "넘어", "이동", "진행", "가자", "갈게", "시작", "바꿔")
        )
        if action == "next" and request_cue and any(
            cue in normalized for cue in ("다음단계", "그다음", "다음으로")
        ):
            return {
                "decision": "allow",
                "action": "next",
                "target_step": None,
                "mark_current_completed": False,
                "reason": "explicit navigation request",
                "latency_ms": 0.0,
                "review_source": "local_validation",
            }
        if action == "prev" and request_cue and any(
            cue in normalized for cue in ("이전단계", "전단계", "앞단계", "뒤로")
        ):
            return {
                "decision": "allow",
                "action": "prev",
                "target_step": None,
                "mark_current_completed": False,
                "reason": "explicit navigation request",
                "latency_ms": 0.0,
                "review_source": "local_validation",
            }
        if action == "set" and request_cue:
            target = proposed_arguments.get("target_step")
            try:
                target_step = int(target)
            except (TypeError, ValueError):
                return None
            if re.search(rf"(?<!\d){target_step}(?:번)?단계", normalized):
                return {
                    "decision": "allow",
                    "action": "set",
                    "target_step": target_step,
                    "mark_current_completed": False,
                    "reason": "explicit numbered navigation request",
                    "latency_ms": 0.0,
                    "review_source": "local_validation",
                }
        return None

    def _apply_tool_state(self, name: str, result: dict[str, Any]) -> None:
        if not result.get("success"):
            self._last_tool_summary = f"{name} 실행 실패"
            return
        if name == "navigate_cooking_step":
            action = result.get("action")
            current_index = self.current_step or 0
            guided_index = self.guided_step if self.guided_step is not None else current_index
            target_index = guided_index
            if action == "next":
                target_index = min(guided_index + 1, max(0, len(self.recipe_steps) - 1))
            elif action == "prev":
                target_index = max(0, guided_index - 1)
            elif action == "set" and result.get("target_step") is not None:
                target_index = min(
                    max(0, int(result["target_step"]) - 1),
                    max(0, len(self.recipe_steps) - 1),
                )
            if self.current_step == target_index:
                self.pending_navigation = None
                self.guided_step = target_index
                self._last_tool_summary = f"화면 {target_index + 1}단계 이동 확인"
                self._navigation_ack_event.set()
            else:
                self._navigation_ack_event.clear()
                # UI 확인은 비동기적인 보조 상태다. 대화는 검증된 목표 단계로 즉시 진행한다.
                self.guided_step = target_index
                self.pending_navigation = {
                    "action": action,
                    "target_step": target_index + 1,
                    "target_index": target_index,
                    "navigation_id": result.get("navigation_id"),
                    "mark_current_completed": bool(result.get("mark_current_completed")),
                    "completed_step": guided_index + 1,
                    "requested_at": time.time(),
                }
                self._last_tool_summary = f"화면 {target_index + 1}단계 이동 요청(UI 확인 대기)"
        elif name == "control_video":
            self._last_tool_summary = f"영상 {result.get('action', '제어')}"
        elif name == "start_timer":
            timer_id = str(result.get("timer_id") or "")
            if timer_id:
                self.active_timers[timer_id] = {
                    key: result.get(key)
                    for key in ("timer_id", "step", "duration", "label", "message", "started_at", "ends_at")
                }
            self._last_tool_summary = f"{result.get('step')}단계 타이머 {result.get('duration')}초 진행 중"
        else:
            self._last_tool_summary = f"{name} 완료"

    async def _execute_tools(
        self,
        tool_calls: list[dict[str, Any]],
        trace: TurnTrace,
        transcript: str = "",
        navigation_review_task: asyncio.Task[dict[str, Any]] | None = None,
    ) -> list[tuple[str, Any]]:
        """한 LLM round의 function calls를 병렬 실행하고 history/trace에 연결한다."""

        navigation_count = sum(
            1
            for call in tool_calls
            if str((call.get("function") or {}).get("name", "")) == "navigate_cooking_step"
        )

        async def execute_one(call: dict[str, Any]) -> tuple[dict[str, Any], Any]:
            function = call.get("function") or {}
            name = str(function.get("name", ""))
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            self.trace.add_entry(
                "tool_proposal",
                json.dumps(arguments, ensure_ascii=False),
                {"tool": name, "state_before": self._cooking_state_snapshot()},
            )
            review: dict[str, Any] | None = None
            navigation_id: str | None = None
            navigation_target_step: int | None = None
            if name == "navigate_cooking_step":
                if navigation_count != 1:
                    review = {
                        "decision": "clarify",
                        "action": None,
                        "target_step": None,
                        "mark_current_completed": False,
                        "reason": "multiple navigation calls in one model round",
                        "latency_ms": 0.0,
                    }
                else:
                    review = await self._parallel_navigation_review(
                        transcript,
                        arguments,
                        navigation_review_task,
                    )
                logger.info(
                    "[CustomVoice:%s] navigation review turn=%s decision=%s action=%s "
                    "target=%s completed=%s latency_ms=%.1f reason=%s",
                    self.trace.session_id,
                    trace.turn_id,
                    review.get("decision"),
                    review.get("action"),
                    review.get("target_step"),
                    bool(review.get("mark_current_completed")),
                    float(review.get("latency_ms") or 0.0),
                    str(review.get("reason") or "")[:160],
                )
                self.trace.add_entry(
                    "tool_review",
                    json.dumps(review, ensure_ascii=False),
                    {"tool": name, "proposed_arguments": arguments},
                )
                action = review.get("action")
                decision = review.get("decision")
                target_step = review.get("target_step")
                if decision != "allow" or action not in {"next", "prev", "set"}:
                    return call, ToolExecution(
                        {
                            "success": False,
                            "error": "navigation_clarification_required",
                            "reason": review.get("reason") or "단계 이동 의도가 불확실함",
                        },
                        float(review.get("critical_wait_ms") or 0.0),
                        False,
                    )
                if action == "set" and target_step is None:
                    return call, ToolExecution(
                        {
                            "success": False,
                            "error": "navigation_target_required",
                            "reason": "특정 단계 번호를 확인해야 함",
                        },
                        float(review.get("critical_wait_ms") or 0.0),
                        False,
                    )
                arguments = {"action": action}
                if action == "set":
                    arguments["target_step"] = int(target_step)
                elif self.guided_step is not None and self.current_step != self.guided_step:
                    # 화면이 대화보다 뒤처졌을 때 next/prev를 화면 기준으로 실행하면
                    # 대화가 다시 과거 단계로 회귀한다. 대화 기준 목표를 절대 이동으로 보정한다.
                    maximum = max(0, len(self.recipe_steps) - 1)
                    conversational_target = (
                        min(self.guided_step + 1, maximum)
                        if action == "next"
                        else max(self.guided_step - 1, 0)
                    )
                    arguments = {"action": "set", "target_step": conversational_target + 1}
                # UI event보다 먼저 pending 상태와 correlation id를 기록한다.
                # 매우 빠른 브라우저 ack도 이 상태를 보고 정확히 확정할 수 있다.
                navigation_id = uuid4().hex
                arguments["navigation_id"] = navigation_id
                self._apply_tool_state(
                    name,
                    {
                        "success": True,
                        "action": action,
                        "target_step": arguments.get("target_step"),
                        "navigation_id": navigation_id,
                        "mark_current_completed": bool(review.get("mark_current_completed")),
                    },
                )
                navigation_target_step = int(
                    (self.pending_navigation or {}).get("target_step")
                    or ((self.current_step or 0) + 1)
                )
            execution = await self.tools.execute(name, arguments)
            if name == "navigate_cooking_step" and not execution.success:
                pending_id = str((self.pending_navigation or {}).get("navigation_id") or "")
                if navigation_id and pending_id == navigation_id:
                    self.pending_navigation = None
                    self._navigation_ack_event.set()
                self._apply_tool_state(name, execution.result)
            if review is not None and execution.success:
                execution = ToolExecution(
                    {
                        **execution.result,
                        "target_step": navigation_target_step,
                        "mark_current_completed": bool(review.get("mark_current_completed")),
                        "review_reason": str(review.get("reason") or ""),
                    },
                    execution.duration_ms + float(review.get("critical_wait_ms") or 0.0),
                    True,
                )
            return call, execution

        results = await asyncio.gather(*(execute_one(call) for call in tool_calls))
        executions: list[tuple[str, Any]] = []
        for call, execution in results:
            name = str((call.get("function") or {}).get("name", ""))
            if name == "navigate_cooking_step" and execution.success:
                navigation_id = str(execution.result.get("navigation_id") or "")
                pending_id = str((self.pending_navigation or {}).get("navigation_id") or "")
                if self.pending_navigation and (not navigation_id or navigation_id == pending_id):
                    try:
                        await asyncio.wait_for(self._navigation_ack_event.wait(), timeout=0.75)
                    except asyncio.TimeoutError:
                        pass
                pending_id = str((self.pending_navigation or {}).get("navigation_id") or "")
                is_pending = bool(self.pending_navigation) and (
                    not navigation_id or pending_id == navigation_id
                )
                execution = ToolExecution(
                    {
                        **execution.result,
                        "ui_confirmed": not is_pending,
                        "status": "pending" if is_pending else "confirmed",
                        "screen_step": None if self.current_step is None else self.current_step + 1,
                    },
                    execution.duration_ms,
                    execution.success,
                )
            elif name != "navigate_cooking_step":
                self._apply_tool_state(name, execution.result)
            result_json = json.dumps(execution.result, ensure_ascii=False)
            self.messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": result_json})
            executions.append((name, execution))
            trace.tool_calls.append(
                {
                    "name": name,
                    "call_id": call.get("id"),
                    "duration_ms": round(execution.duration_ms, 1),
                    "success": execution.success,
                }
            )
            self.trace.add_entry(
                "tool_result",
                result_json,
                {
                    "tool": name,
                    "call_id": call.get("id"),
                    "state_after": self._cooking_state_snapshot(),
                },
            )
        return executions

    async def _tts_worker(
        self,
        queue: asyncio.Queue[Optional[ScheduledTextChunk]],
        trace: TurnTrace,
        output_token: int,
        response_id: str,
        generation_id: int,
    ) -> None:
        """TTS 요청을 제한적으로 선행 실행하고, 결과는 segment/PCM 순서대로만 전송한다."""

        jobs: asyncio.Queue[_TTSStreamJob | None] = asyncio.Queue()
        semaphore = asyncio.Semaphore(max(1, self.settings.tts_max_inflight_requests))
        synthesis_tasks: list[asyncio.Task[None]] = []

        async def synthesize(
            job_queue: asyncio.Queue[bytes | BaseException | None],
            text: str,
            timing: dict[str, float],
        ) -> None:
            try:
                async with semaphore:
                    timing["synthesis_started_at"] = time.time()
                    if hasattr(self.providers, "stream_synthesize"):
                        async for chunk in self.providers.stream_synthesize(text):
                            if chunk:
                                timing.setdefault("first_chunk_at", time.time())
                                await job_queue.put(chunk)
                    else:
                        chunk = await self.providers.synthesize(text)
                        timing.setdefault("first_chunk_at", time.time())
                        await job_queue.put(chunk)
            except BaseException as exc:
                await job_queue.put(exc)
            finally:
                timing["synthesis_completed_at"] = time.time()
                await job_queue.put(None)

        async def intake() -> None:
            segment_index = 0
            try:
                while True:
                    request = await queue.get()
                    if request is None:
                        break
                    chunk_queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue(maxsize=32)
                    requested_at = time.time()
                    timing: dict[str, float] = {}
                    task = asyncio.create_task(synthesize(chunk_queue, request.text, timing))
                    synthesis_tasks.append(task)
                    await jobs.put(
                        _TTSStreamJob(segment_index, request, chunk_queue, task, requested_at, timing)
                    )
                    segment_index += 1
            finally:
                await jobs.put(None)

        intake_task = asyncio.create_task(intake())
        total_audio_ms = 0.0
        audio_sequence = 0
        previous_tail = b""
        tail_bytes = max(2, int(self.settings.output_sample_rate * 0.005) * 2)
        previous_boundary_audio = b""
        boundary_metrics: list[dict[str, Any]] = []
        segment_metrics: list[dict[str, Any]] = []
        last_job: _TTSStreamJob | None = None
        last_segment_chunk_index = 0

        async def send_pcm(
            pcm_chunk: bytes,
            job: _TTSStreamJob,
            segment_chunk_index: int,
            *,
            boundary: dict[str, Any] | None = None,
        ) -> float:
            nonlocal audio_sequence
            if not pcm_chunk:
                return 0.0
            if trace.first_audio_ts is None:
                trace.first_audio_ts = time.time()
                logger.info(
                    "[CustomVoice:%s] TTS first audio turn=%s bytes=%s ttfa_ms=%.1f request_ms=%.1f",
                    self.trace.session_id,
                    trace.turn_id,
                    len(pcm_chunk),
                    (trace.first_audio_ts - (trace.user_speech_end_ts or trace.first_audio_ts)) * 1000.0,
                    (trace.first_audio_ts - job.requested_at) * 1000.0,
                )
                await self._set_state(SessionState.AGENT_SPEAKING)
            self._playback_response_id = response_id
            chunk_ms = len(pcm_chunk) / 2 / self.settings.output_sample_rate * 1000.0
            await self._send_json(
                {
                    "type": "audio_chunk",
                    "audio": base64.b64encode(pcm_chunk).decode("ascii"),
                    "sample_rate": self.settings.output_sample_rate,
                    "channels": 1,
                    "pcm_format": "s16le",
                    "duration_ms": round(chunk_ms, 1),
                    "response_id": response_id,
                    "generation_id": generation_id,
                    "sequence_number": audio_sequence,
                    "segment_index": job.segment_index,
                    "segment_chunk_index": segment_chunk_index,
                    "text_boundary": job.request.boundary,
                    "text_buffered_ms": round(job.request.buffered_ms, 1),
                    "tts_request_wait_ms": round((time.time() - job.requested_at) * 1000.0, 1),
                    "server_sent_at_ms": round(time.time() * 1000.0, 1),
                    "boundary_metrics": boundary,
                }
            )
            audio_sequence += 1
            return chunk_ms

        try:
            while True:
                job = await jobs.get()
                if job is None:
                    break
                last_job = job
                if not self.output_gate.allows(output_token) or self._active_response_id != response_id:
                    raise asyncio.CancelledError
                logger.info(
                    "[CustomVoice:%s] TTS request turn=%s segment=%s chars=%s boundary=%s buffered_ms=%.1f",
                    self.trace.session_id,
                    trace.turn_id,
                    job.segment_index,
                    len(job.request.text),
                    job.request.boundary,
                    job.request.buffered_ms,
                )
                start_seg_ms = total_audio_ms
                first_sent_at: float | None = None
                seg_audio_ms = 0.0
                segment_chunk_index = 0
                first_output = True

                while True:
                    item = await job.chunks.get()
                    if item is None:
                        break
                    if isinstance(item, BaseException):
                        if isinstance(item, asyncio.CancelledError):
                            raise asyncio.CancelledError
                        raise item
                    if not self.output_gate.allows(output_token) or self._active_response_id != response_id:
                        raise asyncio.CancelledError
                    combined = previous_tail + item
                    if len(combined) <= tail_bytes:
                        previous_tail = combined
                        continue
                    emit, previous_tail = combined[:-tail_bytes], combined[-tail_bytes:]
                    boundary_payload = None
                    if first_output and previous_boundary_audio:
                        stitched, metrics, applied = stitch_pcm_boundary(
                            previous_boundary_audio,
                            emit,
                            self.settings.output_sample_rate,
                        )
                        emit = stitched
                        boundary_payload = {**asdict(metrics), "crossfade_applied": applied}
                        boundary_metrics.append(boundary_payload)
                        logger.info(
                            "[CustomVoice:%s] TTS boundary segment=%s jump=%.4f rms_delta_db=%.2f "
                            "leading_silence_ms=%.1f trailing_silence_ms=%.1f crossfade=%s",
                            self.trace.session_id,
                            job.segment_index,
                            metrics.jump,
                            metrics.rms_ratio_db,
                            metrics.leading_silence_ms,
                            metrics.trailing_silence_ms,
                            applied,
                        )
                        previous_boundary_audio = b""
                    chunk_ms = await send_pcm(
                        emit,
                        job,
                        segment_chunk_index,
                        boundary=boundary_payload,
                    )
                    if first_sent_at is None:
                        first_sent_at = time.time()
                    seg_audio_ms += chunk_ms
                    total_audio_ms += chunk_ms
                    segment_chunk_index += 1
                    last_segment_chunk_index = segment_chunk_index
                    first_output = False

                # 독립 요청의 마지막 5 ms는 다음 요청 첫 PCM과 검사/crossfade할 때까지 보류한다.
                previous_boundary_audio = previous_tail
                previous_tail = b""
                if seg_audio_ms > 0:
                    self._turn_speech_segments.append(
                        (job.request.text, start_seg_ms, start_seg_ms + seg_audio_ms)
                    )
                started_at = job.timing.get("synthesis_started_at")
                first_chunk_at = job.timing.get("first_chunk_at")
                completed_at = job.timing.get("synthesis_completed_at")
                segment_metrics.append(
                    {
                        "segment_index": job.segment_index,
                        "chars": len(job.request.text),
                        "boundary": job.request.boundary,
                        "queue_wait_ms": (
                            round((started_at - job.requested_at) * 1000.0, 1)
                            if started_at is not None else None
                        ),
                        "first_chunk_ms": (
                            round((first_chunk_at - job.requested_at) * 1000.0, 1)
                            if first_chunk_at is not None else None
                        ),
                        "synthesis_ms": (
                            round((completed_at - started_at) * 1000.0, 1)
                            if started_at is not None and completed_at is not None else None
                        ),
                        "playback_send_wait_ms": (
                            round((first_sent_at - first_chunk_at) * 1000.0, 1)
                            if first_sent_at is not None and first_chunk_at is not None else None
                        ),
                        "audio_ms": round(seg_audio_ms, 1),
                    }
                )

            if previous_boundary_audio:
                final_pcm = fade_out_pcm(previous_boundary_audio, self.settings.output_sample_rate)
                # 마지막 tail은 마지막 job의 sequence metadata를 사용한다.
                if last_job is not None:
                    chunk_ms = await send_pcm(final_pcm, last_job, last_segment_chunk_index)
                    total_audio_ms += chunk_ms
            trace.agent_audio_duration_ms = total_audio_ms
            self.trace.runtime_metrics.setdefault("tts", {})[f"turn_{trace.turn_id}"] = {
                "response_id": response_id,
                "generation_id": generation_id,
                "audio_chunks": audio_sequence,
                "audio_duration_ms": round(total_audio_ms, 1),
                "boundaries": boundary_metrics,
                "segments": segment_metrics,
            }
        finally:
            if not intake_task.done():
                intake_task.cancel()
            for task in synthesis_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(intake_task, return_exceptions=True)
            if synthesis_tasks:
                await asyncio.gather(*synthesis_tasks, return_exceptions=True)

    async def _fail_turn(self, trace: TurnTrace, exc: Exception) -> None:
        """provider/파싱 오류를 클라이언트에 알리고 다음 턴을 받을 수 있게 상태를 닫는다."""

        trace.response_completed_ts = time.time()
        if self.trace.active_turn is trace:
            self.trace.finish_turn()
        if self._closed or self._transport_closed:
            logger.info(
                "[CustomVoice:%s] turn=%s cancelled after websocket disconnect",
                self.trace.session_id,
                trace.turn_id,
            )
            return
        message = str(exc) if isinstance(exc, ProviderError) else f"Custom voice pipeline failed: {exc}"
        logger.exception("[CustomVoice:%s] turn=%s failed: %s", self.trace.session_id, trace.turn_id, message)
        await self._send_json({"type": "error", "message": message})
        await self._set_state(SessionState.LISTENING)

    async def _set_state(self, state: SessionState) -> None:
        """FSM 전이를 trace와 UI가 함께 관찰할 수 있는 단일 event로 발행한다."""

        if self.state == state:
            return
        self.state = state
        self.trace.add_entry("state", state.value)
        await self._send_json({"type": "state_changed", "state": state.value})

    async def _send_json(self, payload: dict[str, Any]) -> None:
        """여러 provider task의 WebSocket write가 겹치지 않도록 직렬화한다."""

        if self._closed or self._transport_closed:
            raise asyncio.CancelledError
        async with self._send_lock:
            try:
                await self.websocket.send_json(payload)
            except WebSocketDisconnect as exc:
                self._transport_closed = True
                raise asyncio.CancelledError from exc
            except RuntimeError as exc:
                message = str(exc).lower()
                if "websocket.send" in message and (
                    "websocket.close" in message or "response already completed" in message
                ):
                    self._transport_closed = True
                    raise asyncio.CancelledError from exc
                raise
