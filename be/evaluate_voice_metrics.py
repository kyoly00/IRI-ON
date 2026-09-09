"""Realtime API와 Custom cascade를 같은 지표로 평가하는 CLI.

사용 예:
    python be/evaluate_voice_metrics.py --mode benchmark --architecture custom_cascade
    python be/evaluate_voice_metrics.py --mode compare
    python be/evaluate_voice_metrics.py --mode analyze-logs --architecture both

``benchmark``는 evaluator 배선을 빠르게 확인하는 합성 부하다. 실제 품질 비교에는
두 구현으로 동일한 음성 corpus를 재생한 뒤 ``analyze-logs``를 사용해야 한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import random
import sys
import time
from typing import Any


# 프로젝트 루트가 아닌 ``be`` 폴더에서 실행해도 services import가 되게 한다.
sys.path.append(str(Path(__file__).resolve().parent))

from services.voice_metrics import VoiceMetricsTracker
from custom_voice.noise_evaluation import print_noise_summary, run_noise_suppression_benchmark


# 합성 benchmark는 구조별 예상 지연 구간만 다르고 시나리오와 evaluator는 동일하다.
ARCHITECTURE_PROFILES: dict[str, dict[str, tuple[float, float]]] = {
    "realtime": {
        "stt": (0.08, 0.16),
        "llm": (0.10, 0.20),
        "tts": (0.04, 0.09),
        "finish": (0.08, 0.14),
    },
    "custom_cascade": {
        "stt": (0.15, 0.28),
        "llm": (0.12, 0.25),
        "tts": (0.06, 0.13),
        "finish": (0.10, 0.18),
    },
}


SCENARIOS: list[dict[str, Any]] = [
    {"user": "오늘 잔치국수 만들래", "resp": "좋아! 먼저 손을 씻고 준비되면 말해 줘.", "tokens": 23, "dur": 1800},
    {"user": "다 불렸어", "resp": "잘했어! 이제 물을 넣고 끓이자.", "tokens": 20, "dur": 1400},
    {"user": "3분 타이머 맞춰 줘", "resp": "3분 타이머를 시작했어.", "tokens": 16, "dur": 1600, "tool": "start_timer"},
    {"user": "그다음은 뭐야", "resp": "다음 단계를 화면에 보여 줄게.", "tokens": 19, "dur": 2000, "tool": "navigate_cooking_step"},
    {"user": "완성했어 고마워", "resp": "정말 멋지다! 맛있게 먹어.", "tokens": 18, "dur": 1500},
]


def print_banner(title: str) -> None:
    """CLI 섹션 경계를 일관된 너비로 표시한다."""

    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


def print_metrics_table(summary: dict[str, Any]) -> None:
    """공용 VoiceMetricsTracker summary를 구조와 무관한 표로 출력한다."""

    architecture = summary.get("architecture", "realtime")
    print(
        f"\n[구조] {architecture} | [세션] {summary.get('session_id', 'N/A')} | "
        f"[턴] {summary.get('total_turns', 0)} | "
        f"[예상 Voice UX] {summary.get('estimated_voice_ux_score', 0.0)} / 5.0"
    )
    print("-" * 78)
    print(f"{'Metric':<32} | {'Mean':>9} | {'P50':>9} | {'P90':>9} | {'P95':>9}")
    print("-" * 78)

    labels = [
        ("TTFT", "ttft (time_to_first_token)"),
        ("TTFA", "ttfa (time_to_first_audio)"),
        ("STT latency", "stt_latency"),
        ("E2E turn latency", "e2e_turn_latency"),
        ("Barge-in latency", "barge_in_latency"),
        ("Tool execution latency", "tool_execution_latency"),
    ]
    latencies = summary.get("latency_metrics_ms", {})
    for label, key in labels:
        stats = latencies.get(key, {})
        values = [f"{stats.get(percentile):.1f}ms" if stats.get(percentile) is not None else "-" for percentile in ("mean", "p50", "p90", "p95")]
        print(f"{label:<32} | {values[0]:>9} | {values[1]:>9} | {values[2]:>9} | {values[3]:>9}")

    tool_metrics = summary.get("tool_call_metrics", {})
    throughput = summary.get("throughput_and_efficiency", {})
    tps = throughput.get("tokens_per_second (tps)", {}).get("mean")
    rtf = throughput.get("real_time_factor (rtf)", {}).get("mean")
    print("-" * 78)
    print(f"TPS mean: {tps if tps is not None else '-'}")
    print(f"RTF mean: {rtf if rtf is not None else '-'}")
    print(
        f"Tool success: {tool_metrics.get('success_rate_pct', '-')}% "
        f"({tool_metrics.get('total_calls', 0)} calls)"
    )


def run_synthetic_benchmark(architecture: str) -> dict[str, Any]:
    """동일 시나리오로 선택 구조의 측정/요약 코드가 정상 연결됐는지 확인한다."""

    if architecture not in ARCHITECTURE_PROFILES:
        raise ValueError(f"Unsupported architecture: {architecture}")
    print_banner(f"Synthetic voice benchmark: {architecture}")
    profile = ARCHITECTURE_PROFILES[architecture]
    tracker = VoiceMetricsTracker(session_id=f"sim_{architecture}_001")

    # CI와 로컬에서 비교 결과가 재현되도록 구조 이름으로 난수 seed를 고정한다.
    random.seed(architecture)
    for index, scenario in enumerate(SCENARIOS, start=1):
        print(f"[Turn {index}] {scenario['user']}")
        tracker.start_turn(turn_id=index)
        time.sleep(0.005)
        tracker.mark_user_speech_end(audio_duration_ms=scenario["dur"])

        time.sleep(random.uniform(*profile["stt"]))
        tracker.mark_stt_completed(transcript=scenario["user"])

        if scenario.get("tool"):
            call_id = f"{architecture}_call_{index}"
            tracker.start_tool_call(scenario["tool"], call_id)
            time.sleep(0.05)
            tracker.end_tool_call(scenario["tool"], call_id, success=True)

        time.sleep(random.uniform(*profile["llm"]))
        tracker.mark_first_token()
        time.sleep(random.uniform(*profile["tts"]))
        tracker.mark_first_audio()
        time.sleep(random.uniform(*profile["finish"]))
        tracker.end_turn(
            agent_response=scenario["resp"],
            input_tokens=random.randint(120, 200),
            output_tokens=scenario["tokens"],
            agent_audio_duration_ms=scenario["dur"] * 1.2,
        )

    summary = tracker.compute_summary()
    summary["architecture"] = architecture
    print_metrics_table(summary)
    return summary


def compare_summaries(summaries: list[dict[str, Any]]) -> None:
    """A/B 판단에 중요한 p50 지표를 같은 행에 놓아 비교한다."""

    print_banner("Realtime vs Custom cascade (synthetic wiring check)")
    print(f"{'Architecture':<20} | {'STT p50':>10} | {'TTFT p50':>10} | {'TTFA p50':>10} | {'E2E p50':>10}")
    print("-" * 78)
    for summary in summaries:
        latency = summary.get("latency_metrics_ms", {})

        def p50(key: str) -> str:
            value = latency.get(key, {}).get("p50")
            return f"{value:.1f}ms" if value is not None else "-"

        print(
            f"{summary.get('architecture', 'unknown'):<20} | "
            f"{p50('stt_latency'):>10} | "
            f"{p50('ttft (time_to_first_token)'):>10} | "
            f"{p50('ttfa (time_to_first_audio)'):>10} | "
            f"{p50('e2e_turn_latency'):>10}"
        )


def analyze_existing_logs(architecture: str = "both") -> list[dict[str, Any]]:
    """실제 conversation log를 구조별로 필터링해 저장된 metrics summary를 출력한다."""

    log_dir = Path(__file__).resolve().parent / "conversation_logs"
    json_files = sorted(log_dir.glob("*.json"), reverse=True) if log_dir.exists() else []
    if not json_files:
        print(f"분석할 로그가 없습니다: {log_dir}")
        return []

    selected: list[dict[str, Any]] = []
    for path in json_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"로그 읽기 실패 ({path.name}): {exc}")
            continue

        # architecture 필드가 없는 과거 로그는 기존 Realtime 세션으로 간주한다.
        log_architecture = data.get("architecture", "realtime")
        if architecture != "both" and log_architecture != architecture:
            continue
        summary = data.get("metrics_summary")
        if not summary:
            continue
        summary.setdefault("architecture", log_architecture)
        selected.append(summary)

    print_banner(f"Saved session analysis: {architecture} ({len(selected)} sessions)")
    for summary in selected[:10]:
        print_metrics_table(summary)
    return selected


def main() -> None:
    """CLI 인자를 실제/합성 평가 경로로 전달한다."""

    parser = argparse.ArgumentParser(description="Voice AI architecture metrics evaluator")
    parser.add_argument(
        "--mode",
        choices=["benchmark", "compare", "analyze-logs", "noise-suppression"],
        default="benchmark",
        help="합성 단일 평가, 합성 A/B 비교, 저장된 실제 로그 분석",
    )
    parser.add_argument(
        "--architecture",
        choices=["realtime", "custom_cascade", "both"],
        default="both",
        help="평가할 음성 구조",
    )
    parser.add_argument(
        "--corpus-manifest",
        type=Path,
        help="noise-suppression mode에서 사용할 aligned clean/noisy JSONL manifest",
    )
    parser.add_argument(
        "--noise-configs",
        default="no_noise_suppression,browser_ns,browser_aec_rnnoise,browser_aec_deepfilternet",
        help="쉼표로 구분한 noise suppression 실험 configuration",
    )
    parser.add_argument(
        "--skip-stt",
        action="store_true",
        help="외부 STT 비용 없이 VAD/PESQ/STOI/runtime cost만 평가",
    )
    parser.add_argument(
        "--allow-partial-noise-corpus",
        action="store_true",
        help="필수 noise category 일부가 없는 개발용 corpus 허용",
    )
    args = parser.parse_args()

    if args.mode == "noise-suppression":
        if args.corpus_manifest is None:
            parser.error("--mode noise-suppression requires --corpus-manifest")
        configs = [value.strip() for value in args.noise_configs.split(",") if value.strip()]
        results = asyncio.run(
            run_noise_suppression_benchmark(
                args.corpus_manifest,
                configs,
                run_stt=not args.skip_stt,
                allow_partial_corpus=args.allow_partial_noise_corpus,
            )
        )
        print_noise_summary(results)
        output_path = args.corpus_manifest.with_name("noise_suppression_results.json")
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n상세 결과: {output_path}")
        return

    if args.mode == "analyze-logs":
        analyze_existing_logs(args.architecture)
        return
    if args.mode == "compare" or args.architecture == "both":
        summaries = [run_synthetic_benchmark(name) for name in ("realtime", "custom_cascade")]
        compare_summaries(summaries)
        return
    run_synthetic_benchmark(args.architecture)


if __name__ == "__main__":
    main()
