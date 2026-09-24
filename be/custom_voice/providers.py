"""Realtime API 없이 STT, LLM, TTS REST 엔드포인트를 호출하는 provider 계층.

특정 음성 SDK의 session abstraction을 사용하지 않고 일반 HTTP/SSE만 사용한다.
따라서 각 provider는 같은 메서드 계약을 구현하는 다른 서버로 독립 교체할 수 있다.
"""

from __future__ import annotations

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

    def __init__(self, settings: CustomVoiceSettings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._owns_client = client is None
        if client is not None:
            # 테스트와 사내 호환 provider가 transport를 직접 주입할 수 있는 경계다.
            self._client = client
            return

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is not configured")

        # 호환 서버로 교체할 수 있도록 base URL을 환경 변수로 열어 둔다.
        base_url = os.getenv("CUSTOM_VOICE_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(settings.provider_timeout_seconds),
        )

    async def close(self) -> None:
        """세션 종료 시 keep-alive connection pool을 명시적으로 정리한다."""

        if self._owns_client:
            await self._client.aclose()

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
    ) -> AsyncIterator[dict[str, Any]]:
        """Chat Completions의 SSE data frame을 JSON 객체 단위로 yield한다."""

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
            "stream_options": {"include_usage": True},
        }
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

    async def stream_synthesize(self, text: str) -> AsyncIterator[bytes]:
        """TTS API 응답을 aiter_bytes()로 청크 단위 스트리밍하여 생성 즉시 반환한다."""

        async with self._client.stream(
            "POST",
            "/audio/speech",
            json={
                "model": self.settings.tts_model,
                "voice": self.settings.tts_voice,
                "input": text,
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
