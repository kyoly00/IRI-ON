"""Voice AI Agent 핵심 평가지표 측정 및 분석 모듈.

Voice AI Agent에 필수적인 핵심 지표들을 측정하고 집계합니다:
1. TTFT (Time To First Token / First Audio Frame): 사용자 발화 종료 후 첫 토큰/오디오 출력까지의 시간 (ms)
2. STT Latency: 음성 입력 종료 후 텍스트 변환 완료까지의 시간 (ms)
3. E2E Turn Latency: 사용자 발화 종료부터 AI 전체 응답 완료까지의 왕복 시간 (ms)
4. Interruption (Barge-in) Latency: AI 발화 중 사용자 끼어들기 감지 후 중단까지 걸린 시간 (ms)
5. Tool Execution Latency: 도구 호출 결정부터 실행 완료까지의 시간 (ms)
6. Throughput (TPS - Tokens Per Second): 초당 토큰 생성 속도
7. RTF (Real-Time Factor): 오디오 처리 시간 / 오디오 길이 비율 (< 1.0 이어야 실시간)
8. 통계 집계: Mean, Median(P50), P90, P95, Min, Max 및 UX 점수 산출
"""

from dataclasses import dataclass, field
from datetime import datetime
import json
import statistics
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TurnMetrics(BaseModel):
    """단일 대화 턴(Turn)의 성능 측정 지표."""
    turn_id: int
    user_speech_start_ts: Optional[float] = None     # 사용자 발화 시작 (Unix ts)
    user_speech_end_ts: Optional[float] = None       # 사용자 발화 종료/VAD 감지 시점 (Unix ts)
    stt_completed_ts: Optional[float] = None         # STT 변환 완료 시점
    first_token_ts: Optional[float] = None           # LLM 첫 번째 토큰 도착 시점 (TTFT)
    first_audio_ts: Optional[float] = None           # 첫 번째 오디오 청크 도착/재생 시점 (TTFA)
    response_completed_ts: Optional[float] = None    # 전체 응답 완료 시점 (E2E End)
    interruption_ts: Optional[float] = None          # 끼어들기(Barge-in) 감지 시점
    interruption_stopped_ts: Optional[float] = None  # 끼어들기로 오디오 실제 중단된 시점

    # 오디오 및 토큰 정보
    user_audio_duration_ms: Optional[float] = None   # 사용자 입력 음성 길이 (ms)
    agent_audio_duration_ms: Optional[float] = None  # AI 출력 음성 길이 (ms)
    input_tokens: int = 0
    output_tokens: int = 0
    
    # 텍스트 정보
    user_transcript: Optional[str] = None
    agent_response: Optional[str] = None
    
    # 도구 호출 정보
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)  # [{name, duration_ms, success}]

    # --- 계산된 파생 지표 (ms 단위) ---
    @property
    def ttft_ms(self) -> Optional[float]:
        """Time To First Token (ms): 발화 종료 -> 첫 토큰."""
        if self.user_speech_end_ts and self.first_token_ts:
            return max(0.0, (self.first_token_ts - self.user_speech_end_ts) * 1000)
        return None

    @property
    def ttfa_ms(self) -> Optional[float]:
        """Time To First Audio (ms): 발화 종료 -> 첫 오디오 출력 (음성 체감 지연)."""
        if self.user_speech_end_ts and self.first_audio_ts:
            return max(0.0, (self.first_audio_ts - self.user_speech_end_ts) * 1000)
        return None

    @property
    def stt_latency_ms(self) -> Optional[float]:
        """STT Latency (ms): 발화 종료 -> 텍스트 전사 완료."""
        if self.user_speech_end_ts and self.stt_completed_ts:
            return max(0.0, (self.stt_completed_ts - self.user_speech_end_ts) * 1000)
        return None

    @property
    def e2e_latency_ms(self) -> Optional[float]:
        """End-to-End Latency (ms): 발화 종료 -> 전체 응답 완료."""
        if self.user_speech_end_ts and self.response_completed_ts:
            return max(0.0, (self.response_completed_ts - self.user_speech_end_ts) * 1000)
        return None

    @property
    def barge_in_latency_ms(self) -> Optional[float]:
        """Barge-in / Interruption 반응 지연시간 (ms)."""
        if self.interruption_ts and self.interruption_stopped_ts:
            return max(0.0, (self.interruption_stopped_ts - self.interruption_ts) * 1000)
        return None

    @property
    def tokens_per_second(self) -> Optional[float]:
        """초당 출력 토큰 수 (TPS)."""
        if self.first_token_ts and self.response_completed_ts and self.output_tokens > 0:
            gen_time_s = self.response_completed_ts - self.first_token_ts
            if gen_time_s > 0.05:
                return round(self.output_tokens / gen_time_s, 2)
        return None

    @property
    def rtf(self) -> Optional[float]:
        """Real-Time Factor: 처리 시간 / 사용자 오디오 길이 (1.0 미만 시 실시간 처리 만족)."""
        if self.user_audio_duration_ms and self.user_audio_duration_ms > 0 and self.e2e_latency_ms is not None:
            return round(self.e2e_latency_ms / self.user_audio_duration_ms, 3)
        return None

    def to_dict(self) -> Dict[str, Any]:
        """지표 요약 딕셔너리 변환."""
        return {
            "turn_id": self.turn_id,
            "ttft_ms": round(self.ttft_ms, 1) if self.ttft_ms is not None else None,
            "ttfa_ms": round(self.ttfa_ms, 1) if self.ttfa_ms is not None else None,
            "stt_latency_ms": round(self.stt_latency_ms, 1) if self.stt_latency_ms is not None else None,
            "e2e_latency_ms": round(self.e2e_latency_ms, 1) if self.e2e_latency_ms is not None else None,
            "barge_in_latency_ms": round(self.barge_in_latency_ms, 1) if self.barge_in_latency_ms is not None else None,
            "tokens_per_second": self.tokens_per_second,
            "rtf": self.rtf,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls_count": len(self.tool_calls),
            "user_transcript": self.user_transcript,
            "agent_response": (self.agent_response[:60] + "...") if self.agent_response and len(self.agent_response) > 60 else self.agent_response,
        }


class VoiceMetricsTracker:
    """Voice AI 세션의 실시간 지표 수집 및 분석기."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.turns: List[TurnMetrics] = []
        self._current_turn: Optional[TurnMetrics] = None
        self._current_tool_starts: Dict[str, float] = {}

    def start_turn(self, turn_id: Optional[int] = None) -> TurnMetrics:
        """새 턴 시작 및 사용자 발화 감지 준비."""
        tid = turn_id if turn_id is not None else (len(self.turns) + 1)
        turn = TurnMetrics(
            turn_id=tid,
            user_speech_start_ts=time.time(),
        )
        self._current_turn = turn
        return turn

    def mark_user_speech_end(self, audio_duration_ms: Optional[float] = None) -> None:
        """사용자 발화 종료 (VAD End of Speech 감지)."""
        if self._current_turn:
            self._current_turn.user_speech_end_ts = time.time()
            if audio_duration_ms:
                self._current_turn.user_audio_duration_ms = audio_duration_ms

    def mark_stt_completed(self, transcript: Optional[str] = None) -> None:
        """STT 변환 완료."""
        if self._current_turn:
            self._current_turn.stt_completed_ts = time.time()
            if transcript:
                self._current_turn.user_transcript = transcript

    def mark_first_token(self) -> None:
        """LLM 첫 토큰 도착 (TTFT)."""
        if self._current_turn and self._current_turn.first_token_ts is None:
            self._current_turn.first_token_ts = time.time()

    def mark_first_audio(self) -> None:
        """첫 오디오 청크 도착/재생 (TTFA)."""
        if self._current_turn and self._current_turn.first_audio_ts is None:
            self._current_turn.first_audio_ts = time.time()

    def start_tool_call(self, tool_name: str, call_id: str) -> None:
        """도구 호출 시작."""
        self._current_tool_starts[call_id] = time.time()

    def end_tool_call(self, tool_name: str, call_id: str, success: bool = True) -> None:
        """도구 호출 완료 기록."""
        if self._current_turn and call_id in self._current_tool_starts:
            start_ts = self._current_tool_starts.pop(call_id)
            duration_ms = max(0.0, (time.time() - start_ts) * 1000)
            self._current_turn.tool_calls.append({
                "name": tool_name,
                "call_id": call_id,
                "duration_ms": round(duration_ms, 1),
                "success": success,
            })

    def mark_interruption(self) -> None:
        """사용자 끼어들기(Barge-in) 감지."""
        if self._current_turn:
            self._current_turn.interruption_ts = time.time()

    def mark_interruption_stopped(self) -> None:
        """끼어들기로 인한 음성 출력 중단 완료."""
        if self._current_turn:
            self._current_turn.interruption_stopped_ts = time.time()

    def end_turn(
        self,
        agent_response: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        agent_audio_duration_ms: Optional[float] = None,
    ) -> Optional[TurnMetrics]:
        """현재 턴 종료 및 저장."""
        if not self._current_turn:
            return None

        turn = self._current_turn
        turn.response_completed_ts = time.time()
        if agent_response:
            turn.agent_response = agent_response
        turn.input_tokens = input_tokens
        turn.output_tokens = output_tokens
        turn.agent_audio_duration_ms = agent_audio_duration_ms

        self.turns.append(turn)
        self._current_turn = None
        return turn

    @staticmethod
    def _calc_stats(values: List[float]) -> Dict[str, Optional[float]]:
        """수치 리스트로부터 Mean, Median(P50), P90, P95, Min, Max 계산."""
        if not values:
            return {"mean": None, "p50": None, "p90": None, "p95": None, "min": None, "max": None}
        sorted_vals = sorted(values)
        n = len(sorted_vals)

        def percentile(p: float) -> float:
            k = (n - 1) * p
            f = int(k)
            c = f + 1
            if c < n:
                return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])
            return sorted_vals[f]

        return {
            "mean": round(statistics.mean(sorted_vals), 1),
            "p50": round(percentile(0.50), 1),
            "p90": round(percentile(0.90), 1),
            "p95": round(percentile(0.95), 1),
            "min": round(sorted_vals[0], 1),
            "max": round(sorted_vals[-1], 1),
        }

    def compute_summary(self) -> Dict[str, Any]:
        """세션 전체에 대한 핵심 평가지표 종합 요약 및 점수 산출."""
        ttft_list = [t.ttft_ms for t in self.turns if t.ttft_ms is not None]
        ttfa_list = [t.ttfa_ms for t in self.turns if t.ttfa_ms is not None]
        stt_list = [t.stt_latency_ms for t in self.turns if t.stt_latency_ms is not None]
        e2e_list = [t.e2e_latency_ms for t in self.turns if t.e2e_latency_ms is not None]
        barge_in_list = [t.barge_in_latency_ms for t in self.turns if t.barge_in_latency_ms is not None]
        tps_list = [t.tokens_per_second for t in self.turns if t.tokens_per_second is not None]
        rtf_list = [t.rtf for t in self.turns if t.rtf is not None]

        # 도구 실행 지표
        all_tool_calls = [tc for t in self.turns for tc in t.tool_calls]
        tool_latencies = [tc["duration_ms"] for tc in all_tool_calls]
        tool_success_rate = (
            round((sum(1 for tc in all_tool_calls if tc["success"]) / len(all_tool_calls)) * 100, 1)
            if all_tool_calls else None
        )

        total_input_tokens = sum(t.input_tokens for t in self.turns)
        total_output_tokens = sum(t.output_tokens for t in self.turns)

        # Voice UX Score 계산 (5점 만점 기준 ITU-T P.800 / E-Model 간이 환산)
        # - TTFT/TTFA < 800ms: 우수(4.5~5.0), 800~1500ms: 보통(3.5~4.4), > 1500ms: 지연 체감(<3.5)
        avg_ttfa = statistics.mean(ttfa_list) if ttfa_list else (statistics.mean(ttft_list) if ttft_list else None)
        if avg_ttfa is not None:
            if avg_ttfa <= 500:
                ux_score = 5.0
            elif avg_ttfa <= 1000:
                ux_score = round(5.0 - (avg_ttfa - 500) / 500 * 0.8, 2)
            elif avg_ttfa <= 2000:
                ux_score = round(4.2 - (avg_ttfa - 1000) / 1000 * 1.2, 2)
            else:
                ux_score = max(1.0, round(3.0 - (avg_ttfa - 2000) / 2000 * 1.5, 2))
        else:
            ux_score = 4.0

        return {
            "session_id": self.session_id,
            "total_turns": len(self.turns),
            "estimated_voice_ux_score": ux_score,  # 5.0 만점
            "latency_metrics_ms": {
                "ttft (time_to_first_token)": self._calc_stats(ttft_list),
                "ttfa (time_to_first_audio)": self._calc_stats(ttfa_list),
                "stt_latency": self._calc_stats(stt_list),
                "e2e_turn_latency": self._calc_stats(e2e_list),
                "barge_in_latency": self._calc_stats(barge_in_list),
                "tool_execution_latency": self._calc_stats(tool_latencies),
            },
            "throughput_and_efficiency": {
                "tokens_per_second (tps)": self._calc_stats(tps_list),
                "real_time_factor (rtf)": self._calc_stats(rtf_list),
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
            },
            "tool_call_metrics": {
                "total_calls": len(all_tool_calls),
                "success_rate_pct": tool_success_rate,
            },
            "turn_details": [t.to_dict() for t in self.turns],
        }
