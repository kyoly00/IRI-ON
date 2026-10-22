"""sLLM 문맥 분류와 상태 기반 gate로 음성 응답 권한을 제어한다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import re
from typing import Any, Protocol


logger = logging.getLogger(__name__)


class TurnPhase(str, Enum):
    IDLE = "idle"
    USER_SPEAKING = "user_speaking"
    USER_PAUSED = "user_paused"
    WAITING_STT = "waiting_stt"
    THINKING = "thinking"
    ASSISTANT_SPEAKING = "assistant_speaking"
    INTERRUPTING = "interrupting"


@dataclass(frozen=True)
class TurnEvidence:
    speech_duration_ms: float
    silence_duration_ms: float
    transcript: str = ""
    transcript_final: bool = False
    assistant_speaking: bool = False
    speech_probability: float | None = None
    partial_stable: bool = False
    session_state: str = ""


class TurnDetector(Protocol):
    """VAD endpoint와 실제 대화 차례 종료 판단을 분리하는 인터페이스."""

    def should_end_turn(self, evidence: TurnEvidence) -> bool: ...
    def is_backchannel(self, transcript: str) -> bool: ...
    def is_explicit_interrupt(self, transcript: str) -> bool: ...


class KoreanTurnDetector:
    """faster-whisper에 없는 EOU 토큰을 가정하지 않는 보수적 한국어 규칙."""

    _BACKCHANNELS = frozenset({"음", "응", "네", "예", "맞아요", "그렇군요", "아", "어"})
    _INTERRUPTS = ("잠깐", "멈춰", "그만", "다시 설명", "중지", "스톱")

    @staticmethod
    def _normalize(text: str) -> str:
        return "".join(text.strip().lower().rstrip(".!?~。！？").split())

    def is_backchannel(self, transcript: str) -> bool:
        return self._normalize(transcript) in {self._normalize(item) for item in self._BACKCHANNELS}

    def is_explicit_interrupt(self, transcript: str) -> bool:
        normalized = self._normalize(transcript)
        return any(self._normalize(item) in normalized for item in self._INTERRUPTS)

    def should_end_turn(self, evidence: TurnEvidence) -> bool:
        if evidence.transcript_final:
            return bool(evidence.transcript.strip())
        if evidence.speech_duration_ms < 180:
            return False
        # 중간 쉼은 VAD endpoint 하나만으로 확정하지 않는다. 긴 쉼이거나 문장형
        # partial이 있을 때만 이후 구현이 이 신호를 조기 종료에 사용할 수 있다.
        text = evidence.transcript.strip()
        sentence_like = text.endswith(("요", "다", "까", "?", "!", "."))
        return evidence.silence_duration_ms >= (480 if sentence_like else 720)


@dataclass(frozen=True)
class EndpointDecision:
    end_turn: bool
    reason: str | None = None


class EndpointCoordinator:
    """VAD 신호와 STT 의미 단서를 결합해 발화의 끝을 결정한다.

    VAD backend는 이 객체에 음성/무음 프레임만 제공한다. partial STT가 늦거나
    실패해도 fallback/hard timeout으로 turn이 항상 닫히므로 세션이 멈추지 않는다.
    """

    _FILLER_END = re.compile(r"(?:음+|어+|저기|그러니까|그게|뭐랄까)[\s,.…]*$")
    _CONNECTIVE_END = re.compile(
        r"(?:그리고|근데|그래서|그러면(?:요)?|"
        r"는데(?:요)?|지만(?:요)?|려고(?:요)?|다가(?:요)?|면서(?:요)?|"
        r"니까(?:요)?|하면(?:요)?|해서(?:요)?|하고(?:요)?|거나(?:요)?)$"
    )
    _PARTICLE_END = re.compile(r"(?:은|는|이|가|을|를|에|의|와|과)$")
    _COMMAND_ENDINGS = ("해", "줘", "주세요", "해줘", "알려줘", "멈춰", "다시", "다음", "이전")

    def __init__(self, settings: Any, turn_detector: TurnDetector) -> None:
        self.settings = settings
        self.turn_detector = turn_detector
        self._transcript = ""
        self._partial_stable = False

    def reset(self) -> None:
        self._transcript = ""
        self._partial_stable = False

    def update_partial(self, transcript: str, *, stable: bool) -> None:
        self._transcript = transcript.strip()
        self._partial_stable = stable

    def decide(self, evidence: TurnEvidence) -> EndpointDecision:
        if evidence.speech_duration_ms < self.settings.minimum_speech_ms:
            return EndpointDecision(False)
        silence = evidence.silence_duration_ms
        if silence >= self.settings.endpoint_hard_silence_ms:
            return EndpointDecision(True, "hard_silence_timeout")
        if silence < self.settings.endpoint_candidate_silence_ms:
            return EndpointDecision(False)

        text = (evidence.transcript or self._transcript).strip()
        stable = evidence.partial_stable or self._partial_stable
        normalized = re.sub(r"\s+", "", text.lower().rstrip(".!?…"))
        continuation = bool(normalized) and bool(
            self._FILLER_END.search(text.lower())
            or self._CONNECTIVE_END.search(normalized)
            or self._PARTICLE_END.search(normalized)
        )
        sentence_complete = bool(text) and text.rstrip().endswith((".", "!", "?", "요", "다", "죠"))
        explicit_command = bool(normalized) and any(normalized.endswith(item) for item in self._COMMAND_ENDINGS)
        explicit_interrupt = bool(text) and self.turn_detector.is_explicit_interrupt(text)

        # Detector의 silence duration은 이미 probability hysteresis로 계산되지만,
        # 현재 frame이 다시 음성으로 올라온 경우에는 stale silence 값으로 닫지 않는다.
        probability = evidence.speech_probability
        if probability is not None and probability >= self.settings.vad_threshold:
            return EndpointDecision(False)

        if stable and text and not continuation and (
            sentence_complete or explicit_command or explicit_interrupt
        ):
            return EndpointDecision(True, "semantic_endpoint")
        if silence >= self.settings.endpoint_fallback_silence_ms:
            return EndpointDecision(True, "fallback_silence_timeout")
        return EndpointDecision(False)


class CommandIntent(str, Enum):
    HOLD = "hold"
    RELEASE = "release"
    CONFIRM_RELEASE = "confirm_release"
    NOISE = "noise"
    SIDE_TALK = "side_talk"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RouteResult:
    intent: CommandIntent
    confidence: float
    reason: str


class IntentClassifier(Protocol):
    async def classify_intent(self, transcript: str, context: dict[str, Any]) -> dict[str, Any]: ...


class CommandRouter:
    """현재 전사와 이전 대화 전체를 sLLM에 맡기는 비동기 router."""

    async def route(
        self,
        transcript: str,
        *,
        context: dict[str, Any],
        classifier: IntentClassifier,
    ) -> RouteResult:
        try:
            result = await classifier.classify_intent(transcript, context=context)
            intent = CommandIntent(str(result["intent"]).strip().lower())
            confidence = min(1.0, max(0.0, float(result["confidence"])))
            reason = str(result["reason"]).strip()
            return RouteResult(intent=intent, confidence=confidence, reason=reason)
        except Exception as exc:
            # Router 장애가 응답 생성 권한으로 승격되면 안 된다.
            logger.warning("[CommandRouter] sLLM classification failed; denying turn: %s", exc)
            return RouteResult(CommandIntent.UNKNOWN, 0.0, "router_unavailable")


class DialogueMode(str, Enum):
    NORMAL = "normal"
    HOLD = "hold"


class GateAction(str, Enum):
    ALLOW = "allow"
    DROP = "drop"
    ENTER_HOLD = "enter_hold"
    REQUIRE_RELEASE_CONFIRMATION = "require_release_confirmation"
    EXIT_HOLD = "exit_hold"


class OutputGate:
    """취소와 경합한 이전 turn의 텍스트/오디오 출력까지 차단한다."""

    def __init__(self) -> None:
        self._open = True
        self._generation = 0

    def open(self) -> None:
        self._generation += 1
        self._open = True

    def close(self) -> None:
        self._generation += 1
        self._open = False

    def issue_token(self) -> int:
        return self._generation

    def allows(self, token: int) -> bool:
        return self._open and token == self._generation


class ResponseGate:
    """sLLM 판정을 상태 전이로 바꾸되 오류·저신뢰 판정은 항상 폐기한다."""

    def __init__(self, output_gate: OutputGate, minimum_confidence: float = 0.75) -> None:
        self.mode = DialogueMode.NORMAL
        self.release_confirmation_pending = False
        self.output_gate = output_gate
        self.minimum_confidence = minimum_confidence

    def decide(self, route: RouteResult) -> GateAction:
        if route.confidence < self.minimum_confidence or route.intent is CommandIntent.UNKNOWN:
            return GateAction.DROP

        if self.mode is DialogueMode.NORMAL:
            if route.intent is CommandIntent.HOLD:
                self.mode = DialogueMode.HOLD
                self.release_confirmation_pending = False
                self.output_gate.close()
                return GateAction.ENTER_HOLD
            if route.intent in {CommandIntent.NOISE, CommandIntent.SIDE_TALK}:
                return GateAction.DROP
            return GateAction.ALLOW

        if route.intent is CommandIntent.RELEASE:
            self.release_confirmation_pending = True
            return GateAction.REQUIRE_RELEASE_CONFIRMATION
        if self.release_confirmation_pending and route.intent is CommandIntent.CONFIRM_RELEASE:
            self.force_release()
            return GateAction.EXIT_HOLD
        return GateAction.DROP

    def force_hold(self) -> None:
        self.mode = DialogueMode.HOLD
        self.release_confirmation_pending = False
        self.output_gate.close()

    def force_release(self) -> None:
        self.mode = DialogueMode.NORMAL
        self.release_confirmation_pending = False
        self.output_gate.open()

    @property
    def is_holding(self) -> bool:
        return self.mode is DialogueMode.HOLD
