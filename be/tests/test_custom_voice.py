"""외부 API/DB 없이 검증 가능한 Custom cascade 핵심 단위 테스트."""

from __future__ import annotations

import asyncio
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 일부 Windows/Anaconda 조합의 Proactor socketpair 오류를 피해 순수 async 단위 테스트를 안정화한다.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from custom_voice.audio import AdaptiveEnergyEndpointDetector, ProsodyExtractor
from custom_voice.config import CustomVoiceSettings
from custom_voice.privacy import PIIRedactor
from custom_voice.providers import OpenAIHttpProviders, ProviderError
from custom_voice.runtime import SentenceChunker
from custom_voice.runtime import CustomVoiceRuntime
from custom_voice.tracing import CustomTraceStore


class PIIRedactorTests(unittest.TestCase):
    """개인정보가 LLM/log 경계 이전에 제거되는지 확인한다."""

    def test_redacts_korean_pii_patterns(self) -> None:
        redacted = PIIRedactor().redact(
            "주민번호 900101-1234567, 전화 010-1234-5678, 메일 chef@example.com"
        )
        self.assertNotIn("900101", redacted)
        self.assertNotIn("010-1234", redacted)
        self.assertNotIn("chef@example.com", redacted)
        self.assertIn("[주민등록번호]", redacted)
        self.assertIn("[전화번호]", redacted)
        self.assertIn("[이메일]", redacted)


class AudioPipelineTests(unittest.TestCase):
    """PCM framing, 발화 상태 전이, prosody 계산을 deterministic 신호로 검사한다."""

    def test_energy_endpoint_detector_emits_start_and_turn_end(self) -> None:
        settings = CustomVoiceSettings(endpoint_silence_ms=90, minimum_speech_ms=60)
        detector = AdaptiveEnergyEndpointDetector(settings)
        samples_per_frame = settings.input_sample_rate * settings.input_frame_ms // 1000
        silence = np.zeros(samples_per_frame, dtype="<i2").tobytes()
        speech = np.full(samples_per_frame, 3000, dtype="<i2").tobytes()

        events = []
        for frame in [silence, speech, speech, speech, speech, speech, silence, silence, silence]:
            events.extend(detector.push(frame))

        self.assertEqual([event.kind for event in events], ["speech_start", "turn_end"])
        self.assertIsNotNone(events[-1].utterance)
        self.assertGreater(events[-1].duration_ms, 0)

    def test_default_detector_ignores_low_energy_background_noise(self) -> None:
        """실제 장애 trace 수준의 작은 잡음이 greeting/TTS를 취소하지 않아야 한다."""

        settings = CustomVoiceSettings(endpoint_silence_ms=90)
        detector = AdaptiveEnergyEndpointDetector(settings)
        samples_per_frame = settings.input_sample_rate * settings.input_frame_ms // 1000
        low_noise = np.full(samples_per_frame, 500, dtype="<i2").tobytes()

        events = []
        for _ in range(40):
            events.extend(detector.push(low_noise))

        self.assertEqual(events, [])
        self.assertFalse(detector.talking)

    def test_prosody_extractor_returns_bounded_metadata(self) -> None:
        rate = 16_000
        time_axis = np.arange(rate // 2) / rate
        sine = (np.sin(2 * np.pi * 180 * time_axis) * 5000).astype("<i2")
        metadata = ProsodyExtractor(rate).extract(sine.tobytes())

        self.assertIsNotNone(metadata.pitch_mean_hz)
        self.assertGreater(metadata.rms_energy, 0)
        self.assertGreaterEqual(metadata.urgency, 0)
        self.assertLessEqual(metadata.urgency, 1)


class SentenceChunkerTests(unittest.TestCase):
    """LLM delta가 문장 경계에서만 TTS queue로 넘어가는지 확인한다."""

    def test_streaming_sentence_boundaries(self) -> None:
        chunker = SentenceChunker(minimum_chars=5, maximum_chars=30)
        self.assertEqual(chunker.feed("안녕하세요! 다음 "), ["안녕하세요!"])
        self.assertEqual(chunker.feed("단계로 가자."), ["다음 단계로 가자."])
        self.assertIsNone(chunker.flush())


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    """TTS HTTP 계약과 비정상 응답 차단을 실제 socket 없이 검사한다."""

    async def test_tts_request_returns_valid_pcm(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, headers={"content-type": "audio/pcm"}, content=b"\x01\x00" * 20)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://provider.test/v1",
        ) as client:
            provider = OpenAIHttpProviders(CustomVoiceSettings(), client=client)
            pcm = await provider.synthesize("안녕하세요")

        self.assertEqual(captured["path"], "/v1/audio/speech")
        self.assertEqual(captured["payload"]["response_format"], "pcm")
        self.assertEqual(len(pcm), 40)

    async def test_tts_rejects_json_body_even_with_http_200(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "application/json"}, json={"error": "bad voice"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://provider.test/v1",
        ) as client:
            provider = OpenAIHttpProviders(CustomVoiceSettings(), client=client)
            with self.assertRaisesRegex(ProviderError, "non-audio content"):
                await provider.synthesize("안녕하세요")

    async def test_tts_rejects_empty_audio(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "audio/pcm"}, content=b"")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://provider.test/v1",
        ) as client:
            provider = OpenAIHttpProviders(CustomVoiceSettings(), client=client)
            with self.assertRaisesRegex(ProviderError, "empty PCM"):
                await provider.synthesize("안녕하세요")


class TraceStoreTests(unittest.TestCase):
    """실제 custom log가 공용 evaluator schema로 직렬화되는지 확인한다."""

    def test_saves_evaluator_compatible_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CustomTraceStore("session-1", 1, 2, "prompt", Path(temp_dir))
            turn = store.start_turn("speech-1", 10.0)
            turn.user_speech_end_ts = 11.0
            turn.stt_completed_ts = 11.2
            turn.first_token_ts = 11.4
            turn.first_audio_ts = 11.5
            turn.response_completed_ts = 12.0
            turn.user_audio_duration_ms = 1000
            store.finish_turn()

            payload = json.loads(store.save().read_text(encoding="utf-8"))
            self.assertEqual(payload["architecture"], "custom_cascade")
            self.assertEqual(payload["metrics_summary"]["total_turns"], 1)
            self.assertEqual(payload["metrics_summary"]["latency_metrics_ms"]["ttfa (time_to_first_audio)"]["p50"], 500.0)


class _FakeWebSocket:
    """네트워크 없이 runtime outbound protocol을 수집하는 최소 WebSocket 대역."""

    def __init__(self) -> None:
        self.events = []

    async def send_json(self, payload) -> None:
        self.events.append(payload)


class _FakeProviders:
    """LLM 한 문장과 무음 PCM을 반환하는 deterministic provider 대역."""

    async def close(self) -> None:
        return None

    async def transcribe(self, pcm: bytes) -> str:
        return "테스트 발화"

    async def stream_chat(self, messages, tools):
        yield {"choices": [{"delta": {"content": "안녕하세요. 다음 단계를 시작하자!"}}]}
        yield {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 8}}

    async def synthesize(self, text: str) -> bytes:
        return b"\x00\x00" * 2400


class _CountingProviders(_FakeProviders):
    """low-energy gate가 STT 비용까지 막는지 확인하기 위한 호출 계수 provider."""

    def __init__(self) -> None:
        self.transcribe_calls = 0

    async def transcribe(self, pcm: bytes) -> str:
        self.transcribe_calls += 1
        return await super().transcribe(pcm)


class _FailingTTSProviders(_FakeProviders):
    """HTTP TTS 오류가 runtime protocol과 서버 로그로 전파되는 provider."""

    async def synthesize(self, text: str) -> bytes:
        raise ProviderError("TTS failed (400): invalid voice")


class RuntimePipelineTests(unittest.IsolatedAsyncioTestCase):
    """text→streaming LLM→TTS→trace fan-out을 외부 API 없이 통합 검사한다."""

    async def test_text_turn_produces_text_audio_and_metrics(self) -> None:
        websocket = _FakeWebSocket()
        with patch("custom_voice.runtime.OpenAIHttpProviders", return_value=_FakeProviders()):
            runtime = CustomVoiceRuntime(
                websocket=websocket,
                session_id="runtime-test",
                user_id=1,
                recipe_id=2,
                system_prompt="테스트 prompt",
                settings=CustomVoiceSettings(),
            )
        await runtime._begin_text_turn("시작해")
        self.assertIsNotNone(runtime._response_task)
        await runtime._response_task

        event_types = [event["type"] for event in websocket.events]
        self.assertIn("assistant_delta", event_types)
        self.assertIn("audio_chunk", event_types)
        self.assertIn("assistant_done", event_types)
        self.assertEqual(len(runtime.trace.turns), 1)
        self.assertEqual(runtime.trace.turns[0].output_tokens, 8)

    async def test_low_energy_utterance_skips_stt_and_returns_to_listening(self) -> None:
        websocket = _FakeWebSocket()
        providers = _CountingProviders()
        with patch("custom_voice.runtime.OpenAIHttpProviders", return_value=providers):
            runtime = CustomVoiceRuntime(
                websocket=websocket,
                session_id="low-energy-test",
                user_id=1,
                recipe_id=2,
                system_prompt="테스트 prompt",
                settings=CustomVoiceSettings(),
            )
        trace = runtime.trace.start_turn("speech-low")
        low_energy_pcm = np.full(16_000, 500, dtype="<i2").tobytes()

        await runtime._process_audio_turn(low_energy_pcm, trace)

        self.assertEqual(providers.transcribe_calls, 0)
        self.assertEqual(len(runtime.trace.turns), 1)
        self.assertIn("empty_transcript", [event["type"] for event in websocket.events])
        self.assertEqual(runtime.state.value, "listening")

    async def test_tts_failure_is_visible_in_protocol_and_server_log(self) -> None:
        websocket = _FakeWebSocket()
        with patch("custom_voice.runtime.OpenAIHttpProviders", return_value=_FailingTTSProviders()):
            runtime = CustomVoiceRuntime(
                websocket=websocket,
                session_id="tts-failure-test",
                user_id=1,
                recipe_id=2,
                system_prompt="테스트 prompt",
                settings=CustomVoiceSettings(),
            )

        with self.assertLogs("uvicorn.error", level="ERROR") as captured_logs:
            await runtime._begin_text_turn("시작해")
            self.assertIsNotNone(runtime._response_task)
            await runtime._response_task

        errors = [event for event in websocket.events if event["type"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("TTS failed (400)", errors[0]["message"])
        self.assertTrue(any("tts-failure-test" in line for line in captured_logs.output))
        self.assertNotIn("audio_chunk", [event["type"] for event in websocket.events])


if __name__ == "__main__":
    unittest.main()
