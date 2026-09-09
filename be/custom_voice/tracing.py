"""Realtime과 Custom cascade를 같은 필드로 비교하기 위한 E2E trace 저장소."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any, Optional


@dataclass
class TurnTrace:
    """한 사용자 발화에서 발생한 absolute timestamp와 결과를 보관한다."""

    turn_id: int
    speech_id: str
    user_speech_start_ts: Optional[float] = None
    user_speech_end_ts: Optional[float] = None
    stt_completed_ts: Optional[float] = None
    first_token_ts: Optional[float] = None
    first_audio_ts: Optional[float] = None
    response_completed_ts: Optional[float] = None
    interruption_ts: Optional[float] = None
    interruption_stopped_ts: Optional[float] = None
    user_audio_duration_ms: Optional[float] = None
    agent_audio_duration_ms: Optional[float] = None
    input_tokens: int = 0
    output_tokens: int = 0
    user_transcript: Optional[str] = None
    agent_response: Optional[str] = None
    prosody: Optional[dict[str, Any]] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class CustomTraceStore:
    """세션 trace를 메모리에 모으고 종료 시 evaluator 호환 JSON으로 저장한다."""

    architecture = "custom_cascade"

    def __init__(
        self,
        session_id: str,
        user_id: int,
        recipe_id: int,
        system_prompt: str,
        log_dir: Optional[Path] = None,
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.recipe_id = recipe_id
        self.system_prompt = system_prompt
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.ended_at: Optional[str] = None
        self.turns: list[TurnTrace] = []
        self.entries: list[dict[str, Any]] = []
        self.runtime_metrics: dict[str, Any] = {}
        self._active: Optional[TurnTrace] = None
        # 테스트/배포에서 저장 위치를 바꿀 수 있지만 기본값은 기존 평가 로그 폴더다.
        self.log_dir = log_dir or (Path(__file__).resolve().parents[1] / "conversation_logs")

    @property
    def active_turn(self) -> Optional[TurnTrace]:
        """현재 처리 중인 turn을 노출하되 변경 책임은 store에 둔다."""

        return self._active

    def start_turn(self, speech_id: str, speech_started_ts: Optional[float] = None) -> TurnTrace:
        """음성이 검출된 순간 새 turn correlation 객체를 만든다."""

        trace = TurnTrace(
            turn_id=len(self.turns) + 1,
            speech_id=speech_id,
            user_speech_start_ts=speech_started_ts or time.time(),
        )
        self._active = trace
        return trace

    def finish_turn(self) -> None:
        """완료된 turn을 순서대로 확정한다."""

        if self._active is not None:
            self.turns.append(self._active)
            self._active = None

    def add_entry(self, role: str, content: str, metadata: Optional[dict[str, Any]] = None) -> None:
        """PII 제거가 끝난 transcript와 agent/tool 출력을 대화 로그에 추가한다."""

        self.entries.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "role": role,
                "content": content,
                "metadata": metadata,
            }
        )

    def save(self) -> Path:
        """기존 ``evaluate_voice_metrics``가 읽을 수 있는 한 세션 JSON을 기록한다."""

        # import cycle을 피하려고 summary 변환은 저장 시점에만 공용 evaluator 모델을 사용한다.
        from services.voice_metrics import TurnMetrics, VoiceMetricsTracker

        self.ended_at = datetime.now(timezone.utc).isoformat()
        tracker = VoiceMetricsTracker(session_id=self.session_id)
        # 공용 TurnMetrics에는 correlation/prosody 전용 필드가 없으므로 명시적으로 제외한다.
        metric_fields = set(TurnMetrics.model_fields)
        tracker.turns = [
            TurnMetrics(**{key: value for key, value in asdict(turn).items() if key in metric_fields})
            for turn in self.turns
        ]
        summary = tracker.compute_summary()
        summary["architecture"] = self.architecture

        payload = {
            "architecture": self.architecture,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "recipe_id": self.recipe_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "system_prompt": self.system_prompt,
            "entries": self.entries,
            "metrics_summary": summary,
            "runtime_metrics": self.runtime_metrics,
            "turn_traces": [asdict(turn) for turn in self.turns],
        }
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # session_id가 외부에서 오더라도 경로 구분자/예약문자로 log_dir을 벗어나지 못하게 한다.
        safe_session_id = re.sub(r"[^A-Za-z0-9_-]", "_", self.session_id)[:100] or "session"
        path = self.log_dir / f"{stamp}_{self.architecture}_{safe_session_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
