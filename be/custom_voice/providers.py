"""Realtime API 없이 STT, LLM, TTS REST 엔드포인트를 호출하는 provider 계층.

특정 음성 SDK의 session abstraction을 사용하지 않고 일반 HTTP/SSE만 사용한다.
따라서 각 provider는 같은 메서드 계약을 구현하는 다른 서버로 독립 교체할 수 있다.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from typing import Any, AsyncIterator
import wave

import httpx

from .config import CustomVoiceSettings


class ProviderError(RuntimeError):
    """외부 STT/LLM/TTS 응답이 실패했을 때 런타임 경계에서 사용하는 오류."""


class OpenAIHttpProviders:
    """OpenAI의 일반 REST API 세 개를 사용하는 기본 provider 묶음."""

    _shared_clients: dict[tuple[str, str, float], httpx.AsyncClient] = {}

    def __init__(self, settings: CustomVoiceSettings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        if client is not None:
            # 테스트와 사내 호환 provider가 transport를 직접 주입할 수 있는 경계다.
            self._client = client
            self._owns_client = False
            return

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is not configured")

        # 호환 서버로 교체할 수 있도록 base URL을 환경 변수로 열어 둔다.
        base_url = os.getenv("CUSTOM_VOICE_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        client_key = (base_url, api_key, float(settings.provider_timeout_seconds))
        shared = self._shared_clients.get(client_key)
        if shared is None or shared.is_closed:
            shared = httpx.AsyncClient(
                base_url=base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=httpx.Timeout(settings.provider_timeout_seconds),
            )
            self._shared_clients[client_key] = shared
        self._client = shared
        self._owns_client = False

    async def close(self) -> None:
        """공유 transport의 수명은 개별 음성 세션보다 길기 때문에 여기서 닫지 않는다."""

        if self._owns_client:
            await self._client.aclose()

    @classmethod
    async def close_shared_clients(cls) -> None:
        """애플리케이션 종료 시 공유 keep-alive pool을 한 번 정리한다."""

        clients = list(cls._shared_clients.values())
        cls._shared_clients.clear()
        if clients:
            await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)

    @staticmethod
    def _apply_generation_limit(payload: dict[str, Any], model: str, limit: int) -> None:
        """Model family에 맞는 Chat Completions 출력 제한 필드를 적용한다."""
        normalized = model.strip().lower()
        if normalized.startswith(("gpt-5", "o1", "o3", "o4")):
            payload["max_completion_tokens"] = limit
            payload.pop("temperature", None)
        else:
            payload["max_tokens"] = limit

    async def transcribe(self, pcm: bytes, prompt: str | None = None) -> str:
        """16 kHz PCM을 메모리 WAV로 감싼 뒤 일반 transcription API에 보낸다."""

        wav_bytes = self._pcm_to_wav(pcm, self.settings.input_sample_rate)
        data: dict[str, Any] = {
            "model": self.settings.stt_model,
            "language": "ko",
        }
        if prompt:
            data["prompt"] = prompt
        response = await self._client.post(
            "/audio/transcriptions",
            files={"file": ("turn.wav", wav_bytes, "audio/wav")},
            data=data,
        )
        if response.status_code >= 400:
            raise ProviderError(f"STT failed ({response.status_code}): {response.text[:300]}")
        return str(response.json().get("text", "")).strip()

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Chat Completions의 SSE data frame을 JSON 객체 단위로 yield한다."""

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if max_tokens:
            self._apply_generation_limit(payload, self.settings.llm_model, max_tokens)
        async with self._client.stream("POST", "/chat/completions", json=payload) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise ProviderError(f"LLM failed ({response.status_code}): {body[:300]!r}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    yield json.loads(data)
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"Invalid LLM SSE frame: {data[:200]}") from exc

    async def classify_intent(
        self,
        transcript: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """현재 발화가 응답/보류/재개 요청인지 최근 세션 문맥과 함께 분류한다."""

        system_content = (
            "너는 음성 요리 도우미의 의도 분류기다. 답변하지 말고 현재 발화와 제공된 세션 문맥을 함께 분류한다. "
            "hold와 release는 도우미의 음성 응답 상태를 직접 바꾸려는 의도에만 사용하고, UI·미디어·타이머·조리 "
            "제어는 conversation으로 분류한다. confirm_release는 재개 확인에 대한 동의, side_talk는 다른 대상에게 한 말, "
            "noise는 의미 없는 전사다. 근거가 약하면 confidence를 낮춘다."
        )

        user_content = json.dumps(
            {"session_context": context or {}, "current_transcript": transcript},
            ensure_ascii=False,
        )

        payload: dict[str, Any] = {
            "model": self.settings.router_model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "voice_command_route",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "intent": {
                                "type": "string",
                                "enum": [
                                    "conversation",
                                    "side_talk",
                                    "noise",
                                    "hold",
                                    "release",
                                    "confirm_release",
                                ],
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "reason": {"type": "string"},
                        },
                        "required": ["intent", "confidence", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
        }
        self._apply_generation_limit(payload, self.settings.router_model, 200)
        # 라우팅 실패가 UI 명령/응답 전체를 오래 붙잡지 않도록 별도 제한을 둔다.
        timeout = min(self.settings.provider_timeout_seconds, self.settings.router_timeout_seconds)
        response = await self._client.post("/chat/completions", json=payload, timeout=timeout)
        if response.status_code >= 400:
            raise ProviderError(f"Router sLLM failed ({response.status_code}): {response.text[:200]}")
        data = response.json()
        raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Invalid JSON from router sLLM: {raw_text[:200]}") from exc

    async def review_navigation(
        self,
        transcript: str,
        proposed_arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """main LLM과 독립적으로 현재 발화의 단계 이동 의도를 판정한다."""

        system_content = (
            "너는 음성 요리 서비스의 단계 이동 검증기다. 답변하지 말고 JSON만 반환한다. "
            "현재 발화와 session_state에 일관된 이동 근거가 있을 때만 allow하고, 불확실하거나 "
            "상태와 충돌하면 clarify로 판단한다. 화면 위치·안내 이력만으로 완료를 추론하지 말고, 사용자가 말한 "
            "실제 작업과 대화 기준 단계(guided_step)를 우선한다. 사용자가 대화 기준 단계의 조리 작업을 끝냈다는 "
            "발화가 단계 내용과 맞으면 next와 mark_current_completed=true를 허용한다. 사용자가 화면보다 뒤의 인접 "
            "단계 작업을 이미 수행 중이라고 명확히 말했고 제안된 이동이 그 단계와 일치하면, 완료 표시는 하지 않고 "
            "화면 정렬 이동을 허용한다. 손 씻기·도구 준비 같은 시작 전 준비 완료는 레시피 단계 "
            "완료가 아니므로 이동시키지 않는다. 특정 번호가 명시된 경우에만 set으로 다른 단계를 선택한다. "
            "아직 main LLM 제안이 없더라도 현재 발화만으로 action과 target_step을 결정한다. "
            "제안 인자가 제공된 경우에도 현재 발화와 상태를 우선한다. 단계 이동 의도가 없으면 deny를 반환한다."
        )
        payload: dict[str, Any] = {
            "model": self.settings.router_model,
            "messages": [
                {"role": "system", "content": system_content},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_transcript": transcript,
                            "proposed_arguments": proposed_arguments,
                            "session_state": context,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "navigation_review",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "decision": {"type": "string", "enum": ["allow", "deny", "clarify"]},
                            "action": {"type": ["string", "null"], "enum": ["next", "prev", "set", None]},
                            "target_step": {"type": ["integer", "null"], "minimum": 1},
                            "mark_current_completed": {"type": "boolean"},
                            "reason": {"type": "string"},
                        },
                        "required": [
                            "decision",
                            "action",
                            "target_step",
                            "mark_current_completed",
                            "reason",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
        }
        self._apply_generation_limit(payload, self.settings.router_model, 192)
        timeout = min(
            self.settings.provider_timeout_seconds,
            self.settings.navigation_review_timeout_seconds,
        )
        response = await self._client.post("/chat/completions", json=payload, timeout=timeout)
        if response.status_code >= 400:
            raise ProviderError(
                f"Navigation reviewer failed ({response.status_code}): {response.text[:200]}"
            )
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        raw_text = (choice.get("message") or {}).get("content") or ""
        if not raw_text.strip():
            raise ProviderError(
                "Navigation reviewer returned empty content "
                f"(finish_reason={choice.get('finish_reason')!r}, usage={data.get('usage')!r})"
            )
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Invalid JSON from navigation reviewer: {raw_text[:200]}") from exc

    async def stream_synthesize(self, text: str) -> AsyncIterator[bytes]:
        """TTS API 응답을 aiter_bytes()로 청크 단위 스트리밍하여 생성 즉시 반환한다."""

        async with self._client.stream(
            "POST",
            "/audio/speech",
            json={
                "model": self.settings.tts_model,
                "voice": self.settings.tts_voice,
                "input": text,
                "instructions": self.settings.tts_instructions,
                "response_format": "pcm",
                "speed": 1.0,
            },
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise ProviderError(f"TTS failed ({response.status_code}): {body[:300]!r}")
            content_type = response.headers.get("content-type", "").lower()
            if "json" in content_type or content_type.startswith("text/"):
                body = await response.aread()
                raise ProviderError(f"TTS returned non-audio content ({content_type or 'unknown'}): {body[:300]!r}")

            remainder = b""
            # 24kHz 16-bit mono PCM: 1초 = 48,000 bytes.
            # 2,400 bytes = 약 50ms 오디오 청크 단위로 즉시 스트리밍
            async for chunk in response.aiter_bytes(chunk_size=2400):
                if not chunk:
                    continue
                data = remainder + chunk
                # 16-bit (2-byte) sample alignment 유지
                if len(data) % 2 != 0:
                    remainder = data[-1:]
                    data = data[:-1]
                else:
                    remainder = b""
                if data:
                    yield data
            if remainder:
                yield remainder + b"\x00"

    async def synthesize(self, text: str) -> bytes:
        """문장 조각을 24 kHz mono PCM으로 합성해 그대로 반환한다."""

        chunks: list[bytes] = []
        async for chunk in self.stream_synthesize(text):
            chunks.append(chunk)
        pcm = b"".join(chunks)
        if not pcm:
            raise ProviderError("TTS returned an empty PCM response")
        return pcm

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
        """헤더 없는 signed 16-bit mono PCM에 WAV container header를 붙인다."""

        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
        return output.getvalue()
