"""Voice AI Agent 핵심 평가지표 측정 및 벤치마크 평가 스크립트.

실행 방법:
    python be/evaluate_voice_metrics.py --mode benchmark
    python be/evaluate_voice_metrics.py --mode analyze-logs
"""

import argparse
import json
from pathlib import Path
import random
import sys
import time

# 상위 경로 등록
sys.path.append(str(Path(__file__).resolve().parent))

from services.voice_metrics import VoiceMetricsTracker, TurnMetrics


def print_banner(title: str):
    print("\n" + "=" * 70)
    print(f"  📊 {title}")
    print("=" * 70)


def print_metrics_table(summary: dict):
    """지표 요약을 보기 쉬운 표 형태로 터미널에 출력."""
    session_id = summary.get("session_id", "N/A")
    total_turns = summary.get("total_turns", 0)
    ux_score = summary.get("estimated_voice_ux_score", 0.0)
    
    print(f"\n[세션 ID]: {session_id} | [총 대화 턴]: {total_turns}회 | [예상 Voice UX 만족도]: {ux_score} / 5.0")
    print("-" * 70)
    print(f"{'지표명 (Metric)':<32} | {'Mean':>8} | {'P50(Med)':>8} | {'P90':>8} | {'P95':>8}")
    print("-" * 70)

    latencies = summary.get("latency_metrics_ms", {})
    metric_names = [
        ("TTFT (첫 토큰 생성 지연)", "ttft (time_to_first_token)"),
        ("TTFA (첫 오디오 출력 지연)", "ttfa (time_to_first_audio)"),
        ("STT Latency (음성인식 전사)", "stt_latency"),
        ("E2E Turn Latency (전체응답)", "e2e_turn_latency"),
        ("Barge-in Latency (끼어들기)", "barge_in_latency"),
        ("Tool Latency (도구 실행)", "tool_execution_latency"),
    ]

    for label, key in metric_names:
        stats = latencies.get(key, {})
        mean = f"{stats.get('mean')}ms" if stats.get('mean') is not None else "-"
        p50 = f"{stats.get('p50')}ms" if stats.get('p50') is not None else "-"
        p90 = f"{stats.get('p90')}ms" if stats.get('p90') is not None else "-"
        p95 = f"{stats.get('p95')}ms" if stats.get('p95') is not None else "-"
        print(f"{label:<32} | {mean:>8} | {p50:>8} | {p90:>8} | {p95:>8}")

    print("-" * 70)
    tps = summary.get("throughput_and_efficiency", {}).get("tokens_per_second (tps)", {})
    rtf = summary.get("throughput_and_efficiency", {}).get("real_time_factor (rtf)", {})
    print(f"{'생성 속도 (TPS)':<32} | {str(tps.get('mean', '-')) + ' tps':>8} (P50: {str(tps.get('p50', '-'))})")
    print(f"{'실시간 계수 (RTF, <1.0)':<32} | {str(rtf.get('mean', '-')):>8} (P50: {str(rtf.get('p50', '-'))})")
    
    tools = summary.get("tool_call_metrics", {})
    print(f"{'도구 호출 성공률':<32} | {str(tools.get('success_rate_pct', '-')) + '%':>8} (총 {tools.get('total_calls', 0)}회)")
    print("=" * 70 + "\n")


def run_synthetic_benchmark():
    """모의 음성 대화 시나리오(5턴)를 통한 Voice AI Agent 지표 측정 시뮬레이션."""
    print_banner("Voice AI Agent 핵심 평가지표 시뮬레이션 벤치마크")
    
    tracker = VoiceMetricsTracker(session_id="sim_bench_voice_session_001")

    scenarios = [
        {"user": "오늘 떡볶이 만들래", "resp": "좋아! 먼저 떡을 물에 10분 동안 불려놓을까? 준비되면 말해줘.", "tokens": 42, "dur": 1800},
        {"user": "떡 다 불렸어", "resp": "잘했어! 이제 냄비에 물 500ml랑 고추장을 넣고 끓이자. 불 조심해!", "tokens": 48, "dur": 1400},
        {"user": "3분 타이머 맞춰줘", "resp": "3분 타이머 시작했어. 끓는 동안 어묵을 한 입 크기로 썰어보자.", "tokens": 36, "dur": 1600, "tool": "start_timer"},
        {"user": "어묵 다 썰었어 다음은?", "resp": "끓는 양념에 떡과 어묵을 넣고 중불에서 5분간 더 끓여줘.", "tokens": 45, "dur": 2000},
        {"user": "완성됐어 고마워", "resp": "정말 맛있겠다! 그릇에 예쁘게 담고 맛있게 먹어!", "tokens": 30, "dur": 1500},
    ]

    for idx, sc in enumerate(scenarios, 1):
        print(f"👉 [Turn {idx}] 시뮬레이션 중: '{sc['user']}' -> '{sc['resp'][:20]}...'")
        tracker.start_turn(turn_id=idx)
        
        # 1. 사용자 발화 종료 (VAD)
        time.sleep(0.01)
        tracker.mark_user_speech_end(audio_duration_ms=sc["dur"])

        # 2. STT 변환 완료 (평균 150~300ms 시뮬레이션)
        stt_dur = random.uniform(0.15, 0.28)
        time.sleep(stt_dur)
        tracker.mark_stt_completed(transcript=sc["user"])

        # 3. 도구 호출 시뮬레이션 (해당되는 경우)
        if "tool" in sc:
            call_id = f"call_{idx}"
            tracker.start_tool_call(sc["tool"], call_id)
            time.sleep(0.08)
            tracker.end_tool_call(sc["tool"], call_id, success=True)

        # 4. LLM 첫 토큰 도착 (TTFT: 300~600ms)
        llm_ttft = random.uniform(0.12, 0.25)
        time.sleep(llm_ttft)
        tracker.mark_first_token()

        # 5. 첫 오디오 출력 (TTFA: +50~150ms)
        time.sleep(0.08)
        tracker.mark_first_audio()

        # 6. 전체 응답 완료
        time.sleep(0.15)
        tracker.end_turn(
            agent_response=sc["resp"],
            input_tokens=random.randint(120, 200),
            output_tokens=sc["tokens"],
            agent_audio_duration_ms=sc["dur"] * 1.2,
        )

    summary = tracker.compute_summary()
    print_metrics_table(summary)
    return summary


def analyze_existing_logs():
    """저장된 conversation_logs/*.json 파일들을 분석하여 지표 요약."""
    log_dir = Path(__file__).resolve().parent / "conversation_logs"
    if not log_dir.exists():
        print(f"⚠️ 로그 폴더가 존재하지 않습니다: {log_dir}")
        return

    json_files = list(log_dir.glob("*.json"))
    if not json_files:
        print(f"⚠️ {log_dir} 에 저장된 JSON 로그 파일이 없습니다.")
        return

    print_banner(f"저장된 대화 세션 로그 분석 (총 {len(json_files)}개 파일)")
    
    for f in json_files[:5]:  # 최근 5개 파일
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                summary = data.get("metrics_summary")
                session_id = data.get("session_id", f.stem)
                entries = data.get("entries", [])
                
                print(f"📄 파일: {f.name} | 세션: {session_id} | 엔트리 수: {len(entries)}")
                if summary:
                    print_metrics_table(summary)
                else:
                    print("   ℹ️ 이 세션은 metrics_summary가 아직 기록되지 않은 레거시 세션입니다.")
        except Exception as e:
            print(f"❌ 파일 읽기 실패 ({f.name}): {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Voice AI Agent Metrics Evaluator")
    parser.add_argument("--mode", choices=["benchmark", "analyze-logs"], default="benchmark", help="실행 모드")
    args = parser.parse_args()

    if args.mode == "benchmark":
        run_synthetic_benchmark()
    elif args.mode == "analyze-logs":
        analyze_existing_logs()
