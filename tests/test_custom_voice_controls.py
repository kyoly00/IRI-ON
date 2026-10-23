"""외부 서비스 없이 실행하는 음성 응답 제어 핵심 회귀 테스트."""

from pathlib import Path
import asyncio
import atexit
import inspect
import sys
import time
import unittest
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "be"))

from custom_voice.dialogue_control import (  # noqa: E402
    CommandIntent,
    CommandRouter,
    GateAction,
    OutputGate,
    ResponseGate,
    EndpointCoordinator,
    TurnEvidence,
    KoreanTurnDetector,
)
from custom_voice.config import CustomVoiceSettings  # noqa: E402
from custom_voice.tools import (  # noqa: E402
    ToolExecution,
    is_explicit_media_control_request,
    is_navigation_review_candidate,
    select_tool_schemas,
)
from custom_voice.noise_engine import (  # noqa: E402
    AudioFrame,
    NoiseSuppressionEngine,
    NoiseSuppressionStats,
)
from custom_voice.audio import AdaptiveEnergyEndpointDetector  # noqa: E402
from custom_voice.runtime import CustomVoiceRuntime, SentenceChunker  # noqa: E402
from custom_voice.providers import OpenAIHttpProviders  # noqa: E402


_TEST_LOOP: asyncio.AbstractEventLoop | None = None


def _get_test_loop() -> asyncio.AbstractEventLoop:
    global _TEST_LOOP
    if _TEST_LOOP is None or _TEST_LOOP.is_closed():
        for _ in range(5):
            try:
                _TEST_LOOP = asyncio.new_event_loop()
                break
            except OSError:
                time.sleep(0.05)
        else:
            _TEST_LOOP = asyncio.new_event_loop()
        atexit.register(
            lambda: _TEST_LOOP.close()
            if _TEST_LOOP is not None and not _TEST_LOOP.is_closed()
            else None
        )
    return _TEST_LOOP


class SharedLoopAsyncTestCase(unittest.TestCase):
    def _callTestMethod(self, method) -> None:
        if inspect.iscoroutinefunction(method):
            _get_test_loop().run_until_complete(method())
            return
        super()._callTestMethod(method)


class _TestEngine:
    mode = "test"

    def __init__(self) -> None:
        self.stats = NoiseSuppressionStats(mode=self.mode)

    async def process(self, audio_frame: AudioFrame) -> AudioFrame:
        return audio_frame

    async def close(self) -> None:
        return None


class _Classifier:
    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = iter(results)

    async def classify_intent(self, transcript: str, context: dict[str, object]) -> dict[str, object]:
        return next(self.results)


class DialogueControlTests(SharedLoopAsyncTestCase):
    async def test_hold_is_fail_closed_until_confirmed_release(self) -> None:
        router = CommandRouter()
        output = OutputGate()
        gate = ResponseGate(output)
        classifier = _Classifier(
            [
                {"intent": "hold", "confidence": 0.99, "reason": "explicit hold"},
                {"intent": "noise", "confidence": 0.95, "reason": "sound fragment"},
                {"intent": "release", "confidence": 0.96, "reason": "resume request"},
                {"intent": "confirm_release", "confidence": 0.98, "reason": "confirmation"},
            ]
        )

        self.assertEqual(
            gate.decide(await router.route("내가 다 할 때까지 답하지 마", context={}, classifier=classifier)),
            GateAction.ENTER_HOLD,
        )
        self.assertFalse(output.allows(output.issue_token()))
        self.assertEqual(
            gate.decide(await router.route("접시 부딪히는 소리", context={}, classifier=classifier)),
            GateAction.DROP,
        )
        self.assertEqual(
            gate.decide(await router.route("셰프얌 이제 대답해", context={}, classifier=classifier)),
            GateAction.REQUIRE_RELEASE_CONFIRMATION,
        )
        confirmation = await router.route(
            "응",
            context={"release_confirmation_pending": True},
            classifier=classifier,
        )
        self.assertEqual(confirmation.intent, CommandIntent.CONFIRM_RELEASE)
        self.assertEqual(gate.decide(confirmation), GateAction.EXIT_HOLD)
        self.assertTrue(output.allows(output.issue_token()))


class ToolSelectionTests(unittest.TestCase):
    def test_noise_engine_contract_is_structural(self) -> None:
        self.assertIsInstance(_TestEngine(), NoiseSuppressionEngine)

    def test_navigation_schema_is_always_available_to_main_llm(self) -> None:
        names = {schema["function"]["name"] for schema in select_tool_schemas("그다음 알려줘")}
        self.assertIn("navigate_cooking_step", names)

    def test_timer_schema_survives_stt_wording_variants(self) -> None:
        names = {schema["function"]["name"] for schema in select_tool_schemas("20초 타이밍만 맞춰봐")}
        self.assertIn("start_timer", names)

    def test_video_pause_is_ui_control_not_response_hold(self) -> None:
        self.assertTrue(is_explicit_media_control_request("영상 잠깐 멈춰줘"))
        self.assertFalse(is_explicit_media_control_request("내가 말할 때까지 대답 멈춰"))

    def test_explicit_video_command_only_exposes_video_tool(self) -> None:
        names = {
            schema["function"]["name"]
            for schema in select_tool_schemas("영상 잠깐 멈춰줘")
        }
        self.assertEqual(names, {"control_video"})

    def test_navigation_candidate_filter_does_not_execute_or_overmatch_readiness(self) -> None:
        self.assertTrue(is_navigation_review_candidate("양념장을 다 만들었어"))
        self.assertTrue(is_navigation_review_candidate("다음 단계 알려줘"))
        self.assertFalse(is_navigation_review_candidate("손 씻고 왔어"))


class EndpointCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = CustomVoiceSettings()
        self.coordinator = EndpointCoordinator(self.settings, KoreanTurnDetector())

    def evidence(self, silence_ms: float, transcript: str = "", stable: bool = False):
        return TurnEvidence(
            speech_duration_ms=800,
            silence_duration_ms=silence_ms,
            transcript=transcript,
            partial_stable=stable,
            speech_probability=0.01,
        )

    def test_stable_command_ends_at_candidate_silence(self) -> None:
        decision = self.coordinator.decide(self.evidence(280, "다음 단계 알려줘", True))
        self.assertTrue(decision.end_turn)
        self.assertEqual(decision.reason, "semantic_endpoint")

    def test_connective_expression_waits_for_fallback(self) -> None:
        self.assertFalse(self.coordinator.decide(self.evidence(700, "그러니까", True)).end_turn)
        self.assertEqual(
            self.coordinator.decide(self.evidence(720, "그러니까", True)).reason,
            "fallback_silence_timeout",
        )

    def test_rising_speech_probability_cancels_stale_endpoint(self) -> None:
        evidence = TurnEvidence(
            speech_duration_ms=800,
            silence_duration_ms=300,
            transcript="다음 단계 알려줘",
            partial_stable=True,
            speech_probability=self.settings.vad_threshold,
        )
        self.assertFalse(self.coordinator.decide(evidence).end_turn)

    def test_hard_timeout_works_without_partial(self) -> None:
        self.assertEqual(
            self.coordinator.decide(self.evidence(1100)).reason,
            "hard_silence_timeout",
        )

    def test_speech_start_event_preserves_detector_preroll(self) -> None:
        detector = AdaptiveEnergyEndpointDetector(self.settings)
        sample = int(5000).to_bytes(2, "little", signed=True)
        frame = sample * detector.frame_samples
        events = []
        for _ in range(self.settings.speech_start_frames):
            events.extend(detector.push(frame))

        started = next(event for event in events if event.kind == "speech_start")
        self.assertIsNotNone(started.utterance)
        self.assertGreaterEqual(len(started.utterance), len(frame) * self.settings.speech_start_frames)


class SentenceChunkerTests(unittest.TestCase):
    def test_default_does_not_create_tiny_tts_requests(self) -> None:
        chunker = SentenceChunker()

        self.assertEqual(chunker.feed("안녕하세요."), [])
        chunks = chunker.feed(" 지금부터 요리의 다음 단계를 차근차근 안내할게요.")

        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("안녕하세요."))


class RuntimeContextTests(SharedLoopAsyncTestCase):
    def _runtime(self) -> CustomVoiceRuntime:
        runtime = object.__new__(CustomVoiceRuntime)
        runtime.recipe_name = "김치찌개"
        runtime.materials = "김치, 돼지고기, 두부"
        runtime.recipe_metadata = {"time_minutes": 30, "servings": 2, "difficulty": "초급"}
        runtime.recipe_steps = [
            {"step": 1, "text": "재료를 썬다"},
            {"step": 2, "text": "고기를 볶는다"},
            {"step": 3, "text": "물을 붓는다"},
            {"step": 4, "text": "끓인다"},
        ]
        runtime.current_step = 2
        runtime.step_text = "물을 붓는다"
        runtime.guided_step = 2
        runtime.completed_steps = {1}
        runtime.pending_navigation = None
        runtime._navigation_ack_event = asyncio.Event()
        runtime.active_timers = {}
        runtime._last_tool_summary = "영상 pause"
        runtime.settings = CustomVoiceSettings(navigation_review_join_timeout_ms=20)
        runtime.messages = [
            {"role": "system", "content": "role"},
            {"role": "user", "content": "다음"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]},
            {"role": "tool", "content": '{"success":true}'},
            {"role": "assistant", "content": "다음 단계야"},
        ]
        return runtime

    def test_session_state_contains_nearby_steps_and_structured_progress(self) -> None:
        state = self._runtime()._session_state_message()["content"]

        self.assertIn("전체 단계 수: 4", state)
        self.assertIn("2단계", state)
        self.assertIn("3단계", state)
        self.assertIn("4단계", state)
        self.assertIn("현재 화면 단계: 3", state)
        self.assertIn("마지막 안내 단계: 3", state)
        self.assertIn("사용자가 완료했다고 확인한 단계: 1단계", state)
        self.assertIn('"time_minutes": 30', state)

    def test_compact_state_keeps_progress_but_omits_static_metadata(self) -> None:
        state = self._runtime()._session_state_message(compact=True)["content"]

        self.assertIn("현재 화면 단계: 3", state)
        self.assertIn("현재 주변 상세", state)
        self.assertNotIn("기본 메타데이터", state)
        self.assertNotIn("재료 정보", state)

    def test_navigation_waits_for_browser_confirmation(self) -> None:
        runtime = self._runtime()

        runtime._apply_tool_state(
            "navigate_cooking_step",
            {
                "success": True,
                "action": "next",
                "target_step": None,
                "mark_current_completed": True,
            },
        )

        self.assertEqual(runtime.current_step, 2)
        self.assertEqual(runtime.guided_step, 3)
        self.assertEqual(runtime.pending_navigation["target_step"], 4)
        self.assertNotIn(3, runtime.completed_steps)

        runtime._sync_screen_step(3, "볶는다")
        self.assertEqual(runtime.current_step, 3)
        self.assertEqual(runtime.guided_step, 3)
        self.assertIn(3, runtime.completed_steps)
        self.assertIsNone(runtime.pending_navigation)

    def test_same_step_navigation_does_not_complete_recipe_step(self) -> None:
        runtime = self._runtime()
        runtime.current_step = 0
        runtime.guided_step = 0
        runtime.completed_steps = set()

        runtime._apply_tool_state(
            "navigate_cooking_step",
            {
                "success": True,
                "action": "set",
                "target_step": 1,
                "mark_current_completed": False,
            },
        )

        self.assertEqual(runtime.current_step, 0)
        self.assertEqual(runtime.guided_step, 0)
        self.assertEqual(runtime.completed_steps, set())

    def test_spoken_recipe_detail_advances_conversation_without_moving_screen(self) -> None:
        runtime = self._runtime()
        runtime.current_step = 1
        runtime.guided_step = 1

        runtime._update_guided_step_from_response(
            "이제 냄비에 물을 붓는다."
        )

        self.assertEqual(runtime.current_step, 1)
        self.assertEqual(runtime.guided_step, 2)

    def test_navigation_uses_conversational_step_when_screen_is_behind(self) -> None:
        runtime = self._runtime()
        runtime.current_step = 1
        runtime.guided_step = 2

        runtime._apply_tool_state(
            "navigate_cooking_step",
            {"success": True, "action": "next", "mark_current_completed": False},
        )

        self.assertEqual(runtime.current_step, 1)
        self.assertEqual(runtime.guided_step, 3)
        self.assertEqual(runtime.pending_navigation["target_step"], 4)

    def test_explicit_step_in_response_updates_guided_progress(self) -> None:
        runtime = self._runtime()
        runtime.current_step = 0
        runtime.guided_step = 0

        runtime._update_guided_step_from_response("지금은 2단계, 고기를 볶는 중이야.")

        self.assertEqual(runtime.guided_step, 1)

    def test_completed_tool_exchange_is_not_kept_in_history(self) -> None:
        runtime = self._runtime()
        runtime._compact_completed_tool_history()

        self.assertEqual([message["role"] for message in runtime.messages], ["system", "user", "assistant"])

    def test_explicit_navigation_is_locally_validated_without_fixed_response(self) -> None:
        review = self._runtime()._explicit_navigation_review(
            "다음 단계 바로 알려줘",
            {"action": "next"},
        )

        self.assertIsNotNone(review)
        self.assertEqual(review["decision"], "allow")
        self.assertEqual(review["review_source"], "local_validation")

    def test_readiness_is_not_explicit_navigation(self) -> None:
        review = self._runtime()._explicit_navigation_review(
            "손 씻고 왔어",
            {"action": "next"},
        )

        self.assertIsNone(review)

    async def test_parallel_navigation_review_accepts_matching_main_proposal(self) -> None:
        runtime = self._runtime()

        async def completed_review():
            return {
                "decision": "allow",
                "action": "next",
                "target_step": None,
                "mark_current_completed": True,
                "reason": "current work completed",
                "latency_ms": 12.0,
            }

        review = await runtime._parallel_navigation_review(
            "양념장을 다 만들었어",
            {"action": "next"},
            asyncio.create_task(completed_review()),
        )

        self.assertEqual(review["decision"], "allow")
        self.assertEqual(review["review_source"], "parallel_preflight")
        self.assertLess(review["critical_wait_ms"], 50)

    async def test_parallel_navigation_review_blocks_disagreement(self) -> None:
        runtime = self._runtime()

        async def completed_review():
            return {
                "decision": "allow",
                "action": "next",
                "target_step": None,
                "mark_current_completed": True,
                "reason": "completed",
                "latency_ms": 10.0,
            }

        review = await runtime._parallel_navigation_review(
            "양념장을 다 만들었어",
            {"action": "set", "target_step": 3},
            asyncio.create_task(completed_review()),
        )

        self.assertEqual(review["decision"], "clarify")
        self.assertIn("disagreed", review["reason"])

    async def test_navigation_proposal_without_preflight_gets_semantic_review(self) -> None:
        runtime = self._runtime()

        class _Trace:
            session_id = "test-session"

            @staticmethod
            def add_entry(*args, **kwargs):
                return None

        reviewed: dict[str, object] = {}

        async def semantic_review(transcript, proposed_arguments):
            reviewed["transcript"] = transcript
            reviewed["arguments"] = proposed_arguments
            return {
                "decision": "allow",
                "action": "next",
                "target_step": None,
                "mark_current_completed": True,
                "reason": "guided step work completed",
                "latency_ms": 18.0,
            }

        runtime.trace = _Trace()
        runtime._review_navigation_call = semantic_review

        review = await runtime._parallel_navigation_review(
            "스테이크도 썰어 왔어",
            {"action": "next"},
            None,
        )

        self.assertEqual(review["decision"], "allow")
        self.assertEqual(review["review_source"], "on_demand")
        self.assertEqual(reviewed["arguments"], {"action": "next"})

    async def test_navigation_pending_exists_before_ui_event_and_fast_ack_is_confirmed(self) -> None:
        runtime = self._runtime()

        class _Trace:
            session_id = "test-session"

            @staticmethod
            def add_entry(*args, **kwargs):
                return None

        class _Tools:
            async def execute(self, name, arguments):
                self_test.assertEqual(name, "navigate_cooking_step")
                self_test.assertIsNotNone(runtime.pending_navigation)
                self_test.assertEqual(
                    runtime.pending_navigation["navigation_id"],
                    arguments["navigation_id"],
                )
                runtime._sync_screen_step(
                    runtime.pending_navigation["target_index"],
                    navigation_id=arguments["navigation_id"],
                )
                return ToolExecution(
                    {
                        "success": True,
                        "action": arguments["action"],
                        "target_step": None,
                        "navigation_id": arguments["navigation_id"],
                    },
                    1.0,
                    True,
                )

        self_test = self
        runtime.trace = _Trace()
        runtime.tools = _Tools()
        trace = SimpleNamespace(turn_id=1, tool_calls=[])
        call = {
            "id": "call-nav",
            "function": {
                "name": "navigate_cooking_step",
                "arguments": '{"action":"next"}',
            },
        }

        executions = await runtime._execute_tools(
            [call],
            trace,
            transcript="다음 단계 알려줘",
        )

        result = executions[0][1].result
        self.assertEqual(result["status"], "confirmed")
        self.assertTrue(result["ui_confirmed"])
        self.assertEqual(result["screen_step"], 4)
        self.assertIsNone(runtime.pending_navigation)

    async def test_closed_websocket_send_becomes_clean_cancellation(self) -> None:
        runtime = self._runtime()
        runtime._closed = False
        runtime._transport_closed = False
        runtime._send_lock = asyncio.Lock()

        class ClosedSocket:
            async def send_json(self, _payload):
                raise RuntimeError(
                    "Unexpected ASGI message 'websocket.send', after sending 'websocket.close' "
                    "or response already completed."
                )

        runtime.websocket = ClosedSocket()

        with self.assertRaises(asyncio.CancelledError):
            await runtime._send_json({"type": "audio_chunk"})
        self.assertTrue(runtime._transport_closed)

    def test_tool_followup_context_keeps_only_current_exchange(self) -> None:
        runtime = self._runtime()
        runtime.messages.insert(1, {"role": "user", "content": "오래된 질문"})
        runtime.messages.insert(2, {"role": "assistant", "content": "오래된 답변"})

        messages = runtime._llm_messages(tool_followup=True)
        contents = [str(message.get("content") or "") for message in messages]

        self.assertFalse(any("오래된 질문" in content for content in contents))
        self.assertTrue(any("다음" == content for content in contents))
        self.assertNotIn("기본 메타데이터", messages[1]["content"])

    def test_timer_state_keeps_multiple_timer_ids(self) -> None:
        runtime = self._runtime()
        runtime._apply_tool_state(
            "start_timer",
            {"success": True, "timer_id": "one", "step": 2, "duration": 600, "label": "재우기"},
        )
        runtime._apply_tool_state(
            "start_timer",
            {"success": True, "timer_id": "two", "step": 2, "duration": 20, "label": "시험용"},
        )

        self.assertEqual(set(runtime.active_timers), {"one", "two"})

    def test_instruction_request_receives_larger_budget(self) -> None:
        self.assertTrue(self._runtime()._is_instruction_request("다음 단계 알려줘"))
        self.assertFalse(self._runtime()._is_instruction_request("안녕"))


class ProviderPayloadTests(unittest.TestCase):
    def test_gpt5_uses_max_completion_tokens(self) -> None:
        payload = {"temperature": 0.0}
        OpenAIHttpProviders._apply_generation_limit(payload, "gpt-5-nano", 240)

        self.assertEqual(payload["max_completion_tokens"], 240)
        self.assertNotIn("max_tokens", payload)
        self.assertNotIn("temperature", payload)

    def test_gpt4_uses_max_tokens(self) -> None:
        payload = {"temperature": 0.0}
        OpenAIHttpProviders._apply_generation_limit(payload, "gpt-4.1-mini", 140)

        self.assertEqual(payload["max_tokens"], 140)
        self.assertEqual(payload["temperature"], 0.0)

if __name__ == "__main__":
    unittest.main()
