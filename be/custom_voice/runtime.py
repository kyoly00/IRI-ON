"""SDK 독립형 full-duplex 음성 세션 orchestration.

수신 루프는 오디오 framing/VAD만 수행하고, STT→LLM/tools→TTS는 취소 가능한 별도
task에서 실행한다. 따라서 사용자가 말하기 시작하면 진행 중인 생성과 브라우저 재생을
동시에 멈출 수 있다.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict
from enum import Enum
import json
import logging
import time
from typing import Any, Optional
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from .audio import AdaptiveEnergyEndpointDetector, ProsodyExtractor, ProsodyMetadata
from .config import CustomVoiceSettings
from .noise_suppression import (
    AntiAliasResampler,
    AudioFrame,
    NoiseSuppressionError,
    create_noise_suppressor,
)
from .privacy import PIIRedactor
from .providers import OpenAIHttpProviders, ProviderError
from .tools import TOOL_SCHEMAS, ToolExecutor
from .tracing import CustomTraceStore, TurnTrace


# Uvicorn의 handler를 사용해 별도 logging 설정 없이 서버 터미널에 바로 보이게 한다.
logger = logging.getLogger("uvicorn.error")


class SessionState(str, Enum):
    """외부 SDK가 제공하던 대화 상태를 custom runtime의 source of truth로 둔다."""

    CONNECTING = "connecting"
    LISTENING = "listening"
    USER_SPEAKING = "user_speaking"
    THINKING = "thinking"
    AGENT_SPEAKING = "agent_speaking"
    INTERRUPTED = "interrupted"
    CLOSED = "closed"


class SentenceChunker:
    """LLM token delta를 TTS가 자연스럽게 읽을 짧은 문장으로 누적한다."""

    def __init__(self, minimum_chars: int = 16, maximum_chars: int = 110) -> None:
        self.minimum_chars = minimum_chars
        self.maximum_chars = maximum_chars
        self._buffer = ""

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
        return chunks

    def flush(self) -> Optional[str]:
        """LLM 응답이 끝났을 때 남은 짧은 문장을 반환한다."""

        value = self._buffer.strip()
        self._buffer = ""
        return value or None

    def _find_boundary(self) -> Optional[int]:
        """너무 짧은 합성을 피하면서 가장 이른 안전한 문장 경계를 찾는다."""

        if len(self._buffer) >= self.minimum_chars:
            for index, character in enumerate(self._buffer, start=1):
                if index >= self.minimum_chars and character in ".!?。！？\n":
                    return index
        if len(self._buffer) >= self.maximum_chars:
            space = self._buffer.rfind(" ", 0, self.maximum_chars)
            return space + 1 if space >= self.minimum_chars else self.maximum_chars
        return None


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
    ) -> None:
        self.websocket = websocket
        self.settings = settings
        self.detector = AdaptiveEnergyEndpointDetector(settings)
        self.noise_suppressor = create_noise_suppressor(
            settings.noise_suppression,
            rnnoise_library=settings.rnnoise_library,
            deepfilternet_model=settings.deepfilternet_model,
        )
        self.input_resampler = AntiAliasResampler(settings.transport_sample_rate, settings.input_sample_rate)
        self.prosody = ProsodyExtractor(settings.input_sample_rate)
        self.redactor = PIIRedactor()
        self.providers = OpenAIHttpProviders(settings)
        self.trace = CustomTraceStore(session_id, user_id, recipe_id, system_prompt)
        self.tools = ToolExecutor(self._send_json)
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        self._send_lock = asyncio.Lock()
        self._response_task: Optional[asyncio.Task[None]] = None
        self._speech_started_ts: Optional[float] = None
        self._input_sequence = 0
        self._input_sample_index = 0
        self._audio_pipeline_failed = False
        self._closed = False
        self.state = SessionState.CONNECTING

    async def run(self) -> None:
        """handshake 후 오디오/제어 메시지를 받고 종료 시 provider와 trace를 정리한다."""

        await self.websocket.accept()
        logger.info(
            "[CustomVoice:%s] session started user=%s recipe=%s noise_suppression=%s transport_rate=%s",
            self.trace.session_id,
            self.trace.user_id,
            self.trace.recipe_id,
            self.settings.noise_suppression,
            self.settings.transport_sample_rate,
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
                "browser_audio_constraints": self.settings.browser_audio_constraints,
            }
        )
        await self._set_state(SessionState.LISTENING)
        try:
            while True:
                message = await self.websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await self._handle_audio(message["bytes"])
                    continue
                if message.get("text") is not None:
                    should_close = await self._handle_control(message["text"])
                    if should_close:
                        break
        except WebSocketDisconnect:
            pass
        finally:
            await self.close()

    async def close(self) -> None:
        """진행 중 응답을 취소하고 측정 가능한 turn과 connection을 안전하게 마감한다."""

        if self._closed:
            return
        self._closed = True
        if self._response_task and not self._response_task.done():
            self._response_task.cancel()
            await asyncio.gather(self._response_task, return_exceptions=True)
        if self.trace.active_turn is not None:
            self.trace.active_turn.response_completed_ts = time.time()
            self.trace.finish_turn()
        await self.noise_suppressor.close()
        self.trace.runtime_metrics["noise_suppression"] = self.noise_suppressor.stats.summary()
        await self.providers.close()
        path = self.trace.save()
        logger.info("[CustomVoice:%s] session closed trace=%s", self.trace.session_id, path)
        self.state = SessionState.CLOSED

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
        elif message_type in {"text", "timer_complete"}:
            text = str(message.get("text") or message.get("message") or "").strip()
            if text:
                await self._begin_text_turn(text)
        elif message_type == "generate_greeting":
            await self._begin_text_turn(
                "대화를 시작해. 밝게 인사하고, 손을 씻은 뒤 준비되면 말해 달라고 짧게 안내해.",
                internal=True,
            )
        return False

    async def _handle_audio(self, pcm: bytes) -> None:
        """transport PCM에 optional NS/resampling을 적용한 뒤 VAD 상태를 연결한다."""

        if self._audio_pipeline_failed:
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

        for event in self.detector.push(detector_frame.pcm):
            if event.kind == "speech_start":
                self._speech_started_ts = time.time()
                logger.info("[CustomVoice:%s] speech started", self.trace.session_id)
                await self._interrupt_active_response()
                speech_id = uuid4().hex
                self.trace.start_turn(speech_id=speech_id, speech_started_ts=self._speech_started_ts)
                await self._set_state(SessionState.USER_SPEAKING)
                await self._send_json({"type": "user_speech_started", "speech_id": speech_id})
            elif event.kind == "turn_end" and event.utterance:
                trace = self.trace.active_turn
                if trace is None:
                    trace = self.trace.start_turn(uuid4().hex, self._speech_started_ts)
                trace.user_speech_end_ts = time.time()
                trace.user_audio_duration_ms = event.duration_ms
                logger.info(
                    "[CustomVoice:%s] speech ended turn=%s duration_ms=%.1f",
                    self.trace.session_id,
                    trace.turn_id,
                    event.duration_ms,
                )
                await self._set_state(SessionState.THINKING)
                await self._send_json({"type": "user_speech_ended", "speech_id": trace.speech_id})
                self._response_task = asyncio.create_task(self._process_audio_turn(event.utterance, trace))

    async def _begin_text_turn(self, text: str, internal: bool = False) -> None:
        """타이머/초기 인사 같은 text 입력도 동일한 LLM→TTS 파이프라인에 태운다."""

        await self._interrupt_active_response()
        now = time.time()
        trace = self.trace.start_turn(uuid4().hex, now)
        trace.user_speech_end_ts = now
        trace.stt_completed_ts = now
        trace.user_transcript = text
        if not internal:
            self.trace.add_entry("user", self.redactor.redact(text), {"input": "text"})
        await self._set_state(SessionState.THINKING)
        self._response_task = asyncio.create_task(
            self._respond(self.redactor.redact(text), ProsodyMetadata(None, 0.0, "normal", "neutral", 0.0), trace)
        )

    async def _interrupt_active_response(self) -> None:
        """barge-in 시 서버 생성 task와 클라이언트에 예약된 오디오를 함께 중단한다."""

        task = self._response_task
        if not task or task.done():
            return
        interrupted_at = time.time()
        previous = self.trace.active_turn
        if previous is not None:
            previous.interruption_ts = interrupted_at
        await self._set_state(SessionState.INTERRUPTED)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        stopped_at = time.time()
        if previous is not None:
            previous.interruption_stopped_ts = stopped_at
            previous.response_completed_ts = stopped_at
            self.trace.finish_turn()
            logger.info(
                "[CustomVoice:%s] response interrupted turn=%s stop_ms=%.1f",
                self.trace.session_id,
                previous.turn_id,
                (stopped_at - interrupted_at) * 1000.0,
            )
        await self._send_json({"type": "playback_stop"})

    async def _process_audio_turn(self, pcm: bytes, trace: TurnTrace) -> None:
        """STT와 PII/prosody sidecar를 병렬 실행한 뒤 응답 pipeline으로 넘긴다."""

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
            raw_transcript = await self.providers.transcribe(pcm)
            trace.stt_completed_ts = time.time()
            sanitized = self.redactor.redact(raw_transcript)
            trace.user_transcript = sanitized
            if not sanitized:
                trace.response_completed_ts = time.time()
                self.trace.finish_turn()
                await self._send_json({"type": "empty_transcript"})
                await self._set_state(SessionState.LISTENING)
                return
            logger.info(
                "[CustomVoice:%s] STT completed turn=%s text=%r",
                self.trace.session_id,
                trace.turn_id,
                sanitized[:100],
            )
            self.trace.add_entry("user", sanitized, {"prosody": asdict(prosody)})
            await self._send_json(
                {"type": "user_transcript", "speech_id": trace.speech_id, "text": sanitized, "final": True}
            )
            await self._respond(sanitized, prosody, trace)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_turn(trace, exc)

    async def _respond(self, transcript: str, prosody: ProsodyMetadata, trace: TurnTrace) -> None:
        """LLM token을 UI와 sentence TTS queue로 fan-out하고 최종 trace를 확정한다."""

        tts_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        tts_task = asyncio.create_task(self._tts_worker(tts_queue, trace))
        chunker = SentenceChunker()
        response_text = ""
        try:
            # prosody는 별도 system 지시가 아닌 해당 user turn의 제한된 문맥으로만 주입한다.
            self.messages.append({"role": "user", "content": f"{prosody.prompt_hint()}\n{transcript}"})
            for _tool_round in range(3):
                content, tool_calls, usage = await self._stream_one_llm_round(trace, chunker, tts_queue)
                response_text += content
                trace.input_tokens += int(usage.get("prompt_tokens", 0) or 0)
                trace.output_tokens += int(usage.get("completion_tokens", 0) or 0)
                if not tool_calls:
                    self.messages.append({"role": "assistant", "content": content})
                    break

                # assistant tool-call message와 각 tool 결과를 OpenAI 호환 history 형태로 보존한다.
                self.messages.append({"role": "assistant", "content": content or None, "tool_calls": tool_calls})
                await self._execute_tools(tool_calls, trace)

            tail = chunker.flush()
            if tail:
                await tts_queue.put(tail)
            await tts_queue.put(None)
            await tts_task
            trace.agent_response = response_text.strip()
            trace.response_completed_ts = time.time()
            self.trace.add_entry("assistant", trace.agent_response or "", {"is_final": True})
            self.trace.finish_turn()
            await self._send_json({"type": "assistant_done", "text": trace.agent_response or ""})
            await self._set_state(SessionState.LISTENING)
        except asyncio.CancelledError:
            tts_task.cancel()
            await asyncio.gather(tts_task, return_exceptions=True)
            raise
        except Exception as exc:
            tts_task.cancel()
            await asyncio.gather(tts_task, return_exceptions=True)
            await self._fail_turn(trace, exc)

    async def _stream_one_llm_round(
        self,
        trace: TurnTrace,
        chunker: SentenceChunker,
        tts_queue: asyncio.Queue[Optional[str]],
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        """LLM SSE 한 회차에서 text, function arguments, usage를 동시에 조립한다."""

        content_parts: list[str] = []
        tool_parts: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        async for event in self.providers.stream_chat(self.messages, TOOL_SCHEMAS):
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
                await self._send_json({"type": "assistant_delta", "text": content})
                for sentence in chunker.feed(content):
                    await tts_queue.put(sentence)
            for call_delta in delta.get("tool_calls") or []:
                index = int(call_delta.get("index", 0))
                part = tool_parts.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                part["id"] += call_delta.get("id") or ""
                function = call_delta.get("function") or {}
                part["function"]["name"] += function.get("name") or ""
                part["function"]["arguments"] += function.get("arguments") or ""
        return "".join(content_parts), [tool_parts[key] for key in sorted(tool_parts)], usage

    async def _execute_tools(self, tool_calls: list[dict[str, Any]], trace: TurnTrace) -> None:
        """한 LLM round의 function calls를 병렬 실행하고 history/trace에 연결한다."""

        async def execute_one(call: dict[str, Any]) -> tuple[dict[str, Any], Any]:
            function = call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            execution = await self.tools.execute(str(function.get("name", "")), arguments)
            return call, execution

        results = await asyncio.gather(*(execute_one(call) for call in tool_calls))
        for call, execution in results:
            name = str((call.get("function") or {}).get("name", ""))
            result_json = json.dumps(execution.result, ensure_ascii=False)
            self.messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": result_json})
            trace.tool_calls.append(
                {
                    "name": name,
                    "call_id": call.get("id"),
                    "duration_ms": round(execution.duration_ms, 1),
                    "success": execution.success,
                }
            )
            self.trace.add_entry("tool_result", result_json, {"tool": name, "call_id": call.get("id")})

    async def _tts_worker(self, queue: asyncio.Queue[Optional[str]], trace: TurnTrace) -> None:
        """문장 queue를 순서대로 합성해 base64 PCM event로 브라우저에 보낸다."""

        total_audio_ms = 0.0
        while True:
            text = await queue.get()
            if text is None:
                break
            logger.info(
                "[CustomVoice:%s] TTS request turn=%s chars=%s",
                self.trace.session_id,
                trace.turn_id,
                len(text),
            )
            pcm = await self.providers.synthesize(text)
            if trace.first_audio_ts is None:
                trace.first_audio_ts = time.time()
                logger.info(
                    "[CustomVoice:%s] TTS first audio turn=%s bytes=%s ttfa_ms=%.1f",
                    self.trace.session_id,
                    trace.turn_id,
                    len(pcm),
                    (trace.first_audio_ts - (trace.user_speech_end_ts or trace.first_audio_ts)) * 1000.0,
                )
                await self._set_state(SessionState.AGENT_SPEAKING)
            audio_ms = len(pcm) / 2 / self.settings.output_sample_rate * 1000.0
            total_audio_ms += audio_ms
            await self._send_json(
                {
                    "type": "audio_chunk",
                    "audio": base64.b64encode(pcm).decode("ascii"),
                    "sample_rate": self.settings.output_sample_rate,
                    "duration_ms": round(audio_ms, 1),
                }
            )
        trace.agent_audio_duration_ms = total_audio_ms

    async def _fail_turn(self, trace: TurnTrace, exc: Exception) -> None:
        """provider/파싱 오류를 클라이언트에 알리고 다음 턴을 받을 수 있게 상태를 닫는다."""

        trace.response_completed_ts = time.time()
        if self.trace.active_turn is trace:
            self.trace.finish_turn()
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

        async with self._send_lock:
            await self.websocket.send_json(payload)
