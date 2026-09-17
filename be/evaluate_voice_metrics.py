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
import csv
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


# Pricing snapshot supplied by the user on 2026-09-09. All rates are USD per
# 1M tokens and must stay visible here so a saved evaluation is reproducible.
# - GPT-Realtime-2.1 Mini audio: input $10.00, cached input $0.30, output $20.00
# - gpt-4o-mini-transcribe: audio input $1.25, text output $5.00
# - gpt-4.1-mini text: input $0.40, cached input $0.10, output $1.60
# - gpt-4o-mini-tts-2025-12-15: text input $0.60, audio output $12.00
# Realtime text rates ($0.60 input, $0.06 cached input, $2.40 output) are from
# the matching official model card; omitting them would understate Realtime cost.
PRICING_USD_PER_MILLION: dict[str, dict[str, float]] = {
    "gpt-realtime-2.1-mini": {
        "audio_input": 10.00,
        "audio_cached_input": 0.30,
        "audio_output": 20.00,
        "text_input": 0.60,
        "text_cached_input": 0.06,
        "text_output": 2.40,
    },
    "gpt-4o-mini-transcribe": {
        "audio_input": 1.25,
        "text_output": 5.00,
    },
    "gpt-4.1-mini": {
        "text_input": 0.40,
        "text_cached_input": 0.10,
        "text_output": 1.60,
    },
    "gpt-4o-mini-tts-2025-12-15": {
        "text_input": 0.60,
        "audio_output": 12.00,
    },
}

# API usage가 과거 로그에 없는 경우에만 쓰는 명시적 추정 계수다.
# Realtime 공개 환산값($100/M input ~= $0.06/min, $200/M output ~= $0.24/min)
# 에서 각각 10 audio tokens/sec와 20 audio tokens/sec를 역산했다.
AUDIO_INPUT_TOKENS_PER_SECOND = 10.0
AUDIO_OUTPUT_TOKENS_PER_SECOND = 20.0


def _token_cost(tokens: float, usd_per_million: float) -> float:
    """Token 수와 1M token 단가를 USD 비용으로 변환한다."""

    return tokens * usd_per_million / 1_000_000


def _estimate_text_tokens(texts: list[str]) -> int:
    """저장된 문장을 o200k tokenizer로 세어 과거 STT/TTS usage를 보완한다."""

    joined = "\n".join(text for text in texts if text)
    if not joined:
        return 0
    try:
        import tiktoken

        return len(tiktoken.get_encoding("o200k_base").encode(joined))
    except Exception:
        # 첫 실행 때 tokenizer vocabulary 다운로드가 막힌 offline 환경까지 포함한다.
        # 이 fallback도 결과에는 estimated로 표시되므로 provider 측정값과 혼동되지 않는다.
        return max(1, (len(joined) + 1) // 2)


def _finalize_cost(
    architecture: str,
    usage: dict[str, float],
    measurement: str,
    turns: int,
    incomplete_audio_usage: bool = False,
) -> dict[str, Any]:
    """구조별 component 비용과 세션/턴 정규화 비용을 계산한다."""

    components: dict[str, float]
    if architecture == "realtime":
        rates = PRICING_USD_PER_MILLION["gpt-realtime-2.1-mini"]
        components = {
            "realtime_audio_input_usd": _token_cost(usage.get("realtime_audio_input_tokens", 0), rates["audio_input"]),
            "realtime_cached_audio_input_usd": _token_cost(usage.get("realtime_cached_audio_input_tokens", 0), rates["audio_cached_input"]),
            "realtime_audio_output_usd": _token_cost(usage.get("realtime_audio_output_tokens", 0), rates["audio_output"]),
            "realtime_text_input_usd": _token_cost(usage.get("realtime_text_input_tokens", 0), rates["text_input"]),
            "realtime_cached_text_input_usd": _token_cost(usage.get("realtime_cached_text_input_tokens", 0), rates["text_cached_input"]),
            "realtime_text_output_usd": _token_cost(usage.get("realtime_text_output_tokens", 0), rates["text_output"]),
        }
        pricing_scenario = "gpt-realtime-2.1-mini"
    else:
        stt = PRICING_USD_PER_MILLION["gpt-4o-mini-transcribe"]
        llm = PRICING_USD_PER_MILLION["gpt-4.1-mini"]
        tts = PRICING_USD_PER_MILLION["gpt-4o-mini-tts-2025-12-15"]
        components = {
            "stt_audio_input_usd": _token_cost(usage.get("stt_audio_input_tokens", 0), stt["audio_input"]),
            "stt_text_output_usd": _token_cost(usage.get("stt_text_output_tokens", 0), stt["text_output"]),
            "llm_text_input_usd": _token_cost(usage.get("llm_text_input_tokens", 0), llm["text_input"]),
            "llm_cached_text_input_usd": _token_cost(usage.get("llm_cached_text_input_tokens", 0), llm["text_cached_input"]),
            "llm_text_output_usd": _token_cost(usage.get("llm_text_output_tokens", 0), llm["text_output"]),
            "tts_text_input_usd": _token_cost(usage.get("tts_text_input_tokens", 0), tts["text_input"]),
            "tts_audio_output_usd": _token_cost(usage.get("tts_audio_output_tokens", 0), tts["audio_output"]),
        }
        pricing_scenario = "gpt-4o-mini-transcribe + gpt-4.1-mini + gpt-4o-mini-tts-2025-12-15"

    total = sum(components.values())
    if architecture == "realtime":
        pricing_rates: dict[str, Any] = {
            "gpt-realtime-2.1-mini": PRICING_USD_PER_MILLION["gpt-realtime-2.1-mini"]
        }
    else:
        pricing_rates = {
            model: PRICING_USD_PER_MILLION[model]
            for model in (
                "gpt-4o-mini-transcribe",
                "gpt-4.1-mini",
                "gpt-4o-mini-tts-2025-12-15",
            )
        }
    return {
        "currency": "USD",
        "pricing_scenario": pricing_scenario,
        "pricing_rates_usd_per_million_tokens": pricing_rates,
        "measurement": measurement,
        "incomplete_audio_usage": incomplete_audio_usage,
        "usage": {key: round(value, 3) for key, value in usage.items()},
        "component_cost_usd": {key: round(value, 8) for key, value in components.items()},
        "total_cost_usd": round(total, 8),
        "cost_per_turn_usd": round(total / turns, 8) if turns else None,
        "cost_per_100_turns_usd": round(total / turns * 100, 6) if turns else None,
    }


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


def _summary_to_table_row(summary: dict[str, Any], evaluation_type: str) -> dict[str, Any]:
    """Nested metrics summary를 CSV에서 바로 비교할 수 있는 한 행으로 평탄화한다."""

    latency = summary.get("latency_metrics_ms", {})
    throughput = summary.get("throughput_and_efficiency", {})
    tools = summary.get("tool_call_metrics", {})
    noise = summary.get("runtime_metrics", {}).get("noise_suppression", {})
    cost = summary.get("cost_evaluation", {})
    cost_usage = cost.get("usage", {})
    component_cost = cost.get("component_cost_usd", {})

    def component_total(prefix: str) -> float | None:
        values = [float(value) for key, value in component_cost.items() if key.startswith(prefix)]
        return round(sum(values), 8) if values else None

    def latency_value(key: str, statistic: str) -> Any:
        return latency.get(key, {}).get(statistic)

    row: dict[str, Any] = {
        "evaluation_type": evaluation_type,
        "architecture": summary.get("architecture", "realtime"),
        "session_id": summary.get("session_id"),
        "total_turns": summary.get("total_turns", 0),
        "metrics_available": summary.get("metrics_available", bool(latency)),
        "estimated_voice_ux_score": summary.get("estimated_voice_ux_score"),
    }
    for prefix, key in (
        ("ttft_ms", "ttft (time_to_first_token)"),
        ("ttfa_ms", "ttfa (time_to_first_audio)"),
        ("stt_latency_ms", "stt_latency"),
        ("e2e_latency_ms", "e2e_turn_latency"),
        ("barge_in_latency_ms", "barge_in_latency"),
        ("tool_latency_ms", "tool_execution_latency"),
    ):
        for statistic in ("mean", "p50", "p90", "p95"):
            row[f"{prefix}_{statistic}"] = latency_value(key, statistic)

    row.update({
        "tps_mean": throughput.get("tokens_per_second (tps)", {}).get("mean"),
        "rtf_mean": throughput.get("real_time_factor (rtf)", {}).get("mean"),
        "total_input_tokens": throughput.get("total_input_tokens"),
        "total_output_tokens": throughput.get("total_output_tokens"),
        "tool_calls": tools.get("total_calls", 0),
        "tool_success_rate_pct": tools.get("success_rate_pct"),
        "noise_suppression_mode": noise.get("mode"),
        "noise_processing_latency_ms_mean": noise.get("processing_latency_ms_mean"),
        "noise_realtime_factor": noise.get("realtime_factor"),
        "noise_cpu_usage_pct": noise.get("cpu_usage_pct_during_processing"),
        "pricing_scenario": cost.get("pricing_scenario"),
        "cost_measurement": cost.get("measurement"),
        "cost_incomplete_audio_usage": cost.get("incomplete_audio_usage"),
        "total_cost_usd": cost.get("total_cost_usd"),
        "cost_per_turn_usd": cost.get("cost_per_turn_usd"),
        "cost_per_100_turns_usd": cost.get("cost_per_100_turns_usd"),
        "realtime_cost_usd": component_total("realtime_"),
        "stt_cost_usd": component_total("stt_"),
        "llm_cost_usd": component_total("llm_"),
        "tts_cost_usd": component_total("tts_"),
        "realtime_audio_input_tokens": cost_usage.get("realtime_audio_input_tokens"),
        "realtime_audio_output_tokens": cost_usage.get("realtime_audio_output_tokens"),
        "realtime_text_input_tokens": cost_usage.get("realtime_text_input_tokens"),
        "realtime_text_output_tokens": cost_usage.get("realtime_text_output_tokens"),
        "stt_audio_input_tokens": cost_usage.get("stt_audio_input_tokens"),
        "stt_text_output_tokens": cost_usage.get("stt_text_output_tokens"),
        "llm_text_input_tokens": cost_usage.get("llm_text_input_tokens"),
        "llm_text_output_tokens": cost_usage.get("llm_text_output_tokens"),
        "tts_text_input_tokens": cost_usage.get("tts_text_input_tokens"),
        "tts_audio_output_tokens": cost_usage.get("tts_audio_output_tokens"),
    })
    return row


def save_summary_tables(
    summaries: list[dict[str, Any]],
    output_dir: Path,
    stem: str,
    evaluation_type: str,
) -> tuple[Path, Path]:
    """평가 결과를 사람이 보기 쉬운 CSV와 원본 보존용 JSON으로 함께 저장한다."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [_summary_to_table_row(summary, evaluation_type) for summary in summaries]
    csv_path = output_dir / f"{stem}.csv"
    json_path = output_dir / f"{stem}.json"

    if rows:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("evaluation_type,architecture,session_id,total_turns\n", encoding="utf-8-sig")
    json_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nCSV table: {csv_path}")
    print(f"JSON details: {json_path}")
    return csv_path, json_path


def _attach_synthetic_cost(summary: dict[str, Any], architecture: str) -> None:
    """동일 synthetic 발화 길이와 token workload에 가격 시나리오를 적용한다."""

    throughput = summary.get("throughput_and_efficiency", {})
    user_audio_seconds = sum(float(scenario["dur"]) for scenario in SCENARIOS) / 1000
    agent_audio_seconds = sum(float(scenario["dur"]) * 1.2 for scenario in SCENARIOS) / 1000
    llm_input_tokens = float(throughput.get("total_input_tokens") or 0)
    llm_output_tokens = float(throughput.get("total_output_tokens") or 0)

    if architecture == "realtime":
        usage = {
            "realtime_audio_input_tokens": user_audio_seconds * AUDIO_INPUT_TOKENS_PER_SECOND,
            "realtime_cached_audio_input_tokens": 0,
            "realtime_audio_output_tokens": agent_audio_seconds * AUDIO_OUTPUT_TOKENS_PER_SECOND,
            "realtime_text_input_tokens": llm_input_tokens,
            "realtime_cached_text_input_tokens": 0,
            "realtime_text_output_tokens": llm_output_tokens,
        }
    else:
        usage = {
            "stt_audio_input_tokens": user_audio_seconds * AUDIO_INPUT_TOKENS_PER_SECOND,
            "stt_text_output_tokens": _estimate_text_tokens([str(item["user"]) for item in SCENARIOS]),
            "llm_text_input_tokens": llm_input_tokens,
            "llm_cached_text_input_tokens": 0,
            "llm_text_output_tokens": llm_output_tokens,
            "tts_text_input_tokens": _estimate_text_tokens([str(item["resp"]) for item in SCENARIOS]),
            "tts_audio_output_tokens": agent_audio_seconds * AUDIO_OUTPUT_TOKENS_PER_SECOND,
        }
    summary["cost_evaluation"] = _finalize_cost(
        architecture,
        usage,
        measurement="synthetic_estimate_no_cached_tokens",
        turns=int(summary.get("total_turns", 0)),
    )


def _attach_actual_cost(summary: dict[str, Any], data: dict[str, Any]) -> None:
    """저장된 provider usage 또는 audio duration으로 실제 세션 비용을 계산한다."""

    architecture = str(summary.get("architecture", "realtime"))
    turns = int(summary.get("total_turns", 0))
    if architecture == "realtime":
        token_usage = data.get("token_usage") or {}
        usage = {
            "realtime_audio_input_tokens": float(token_usage.get("input_audio_tokens") or 0),
            "realtime_cached_audio_input_tokens": 0,
            "realtime_audio_output_tokens": float(token_usage.get("output_audio_tokens") or 0),
            "realtime_text_input_tokens": float(token_usage.get("input_text_tokens") or 0),
            "realtime_cached_text_input_tokens": 0,
            "realtime_text_output_tokens": float(token_usage.get("output_text_tokens") or 0),
        }
        summary["cost_evaluation"] = _finalize_cost(
            architecture,
            usage,
            measurement="measured_tokens_repriced_upper_bound_cached_split_unavailable",
            turns=turns,
        )
        return

    turn_traces = data.get("turn_traces") or []
    user_audio_ms = sum(float(turn.get("user_audio_duration_ms") or 0) for turn in turn_traces)
    agent_audio_ms = sum(float(turn.get("agent_audio_duration_ms") or 0) for turn in turn_traces)
    stt_texts = [
        str(turn.get("user_transcript") or "")
        for turn in turn_traces
        if turn.get("user_audio_duration_ms")
    ]
    tts_texts = [
        str(turn.get("agent_response") or "")
        for turn in turn_traces
        if turn.get("agent_audio_duration_ms")
    ]
    throughput = summary.get("throughput_and_efficiency", {})
    usage = {
        "stt_audio_input_tokens": user_audio_ms / 1000 * AUDIO_INPUT_TOKENS_PER_SECOND,
        "stt_text_output_tokens": _estimate_text_tokens(stt_texts),
        "llm_text_input_tokens": float(throughput.get("total_input_tokens") or 0),
        "llm_cached_text_input_tokens": 0,
        "llm_text_output_tokens": float(throughput.get("total_output_tokens") or 0),
        "tts_text_input_tokens": _estimate_text_tokens(tts_texts),
        "tts_audio_output_tokens": agent_audio_ms / 1000 * AUDIO_OUTPUT_TOKENS_PER_SECOND,
    }
    incomplete_audio = any(
        int(turn.get("output_tokens") or 0) > 0 and turn.get("agent_audio_duration_ms") is None
        for turn in turn_traces
    )
    summary["cost_evaluation"] = _finalize_cost(
        architecture,
        usage,
        measurement="mixed_measured_llm_tokens_and_estimated_audio_tokens",
        turns=turns,
        incomplete_audio_usage=incomplete_audio,
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
    _attach_synthetic_cost(summary, architecture)
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


def print_cost_balance_table(summaries: list[dict[str, Any]], title: str) -> None:
    """Latency와 비용을 같은 행에 놓아 구조 선택의 trade-off를 표시한다."""

    print_banner(title)
    print(
        f"{'Architecture':<16} | {'Turns':>5} | {'E2E p50':>10} | {'UX':>5} | "
        f"{'Session USD':>11} | {'USD/turn':>10} | {'USD/100 turns':>13} | {'Basis':<18}"
    )
    print("-" * 112)
    for summary in summaries:
        e2e = summary.get("latency_metrics_ms", {}).get("e2e_turn_latency", {}).get("p50")
        cost = summary.get("cost_evaluation", {})
        measurement = str(cost.get("measurement") or "-")
        print(
            f"{summary.get('architecture', 'unknown'):<16} | "
            f"{int(summary.get('total_turns', 0)):>5} | "
            f"{(f'{e2e:.1f}ms' if e2e is not None else '-'):>10} | "
            f"{str(summary.get('estimated_voice_ux_score', '-')):>5} | "
            f"{str(cost.get('total_cost_usd', '-')):>11} | "
            f"{str(cost.get('cost_per_turn_usd', '-')):>10} | "
            f"{str(cost.get('cost_per_100_turns_usd', '-')):>13} | "
            f"{measurement[:18]:<18}"
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
            token_usage = data.get("token_usage") or {}
            if log_architecture != "realtime" or int(token_usage.get("total_tokens") or 0) <= 0:
                continue
            # 기존 Realtime 로그는 성능 timestamp가 없지만 billing token은 있으므로
            # 비용 전용 row로 포함한다. metrics_available=false로 오해를 방지한다.
            entries = data.get("entries") or []
            summary = {
                "session_id": data.get("session_id"),
                "architecture": "realtime",
                "total_turns": sum(1 for entry in entries if entry.get("role") == "user"),
                "metrics_available": False,
                "latency_metrics_ms": {},
                "throughput_and_efficiency": {
                    "total_input_tokens": token_usage.get("input_tokens", 0),
                    "total_output_tokens": token_usage.get("output_tokens", 0),
                },
                "tool_call_metrics": {},
            }
        else:
            summary.setdefault("architecture", log_architecture)
            summary["metrics_available"] = True
        # Custom runtime의 noise processing 비용도 같은 session row에 포함한다.
        if data.get("runtime_metrics"):
            summary["runtime_metrics"] = data["runtime_metrics"]
        _attach_actual_cost(summary, data)
        selected.append(summary)

    print_banner(f"Saved session analysis: {architecture} ({len(selected)} sessions)")
    for summary in selected[:10]:
        if summary.get("metrics_available"):
            print_metrics_table(summary)
    print_cost_balance_table(selected[:20], "Actual log performance-cost balance")
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
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "evaluation_results",
        help="CSV/JSON 평가 결과 저장 디렉터리",
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
        summaries = analyze_existing_logs(args.architecture)
        save_summary_tables(summaries, args.output_dir, "actual_session_metrics", "actual_log")
        return
    if args.mode == "compare" or args.architecture == "both":
        summaries = [run_synthetic_benchmark(name) for name in ("realtime", "custom_cascade")]
        compare_summaries(summaries)
        print_cost_balance_table(summaries, "Synthetic performance-cost balance")
        save_summary_tables(summaries, args.output_dir, "synthetic_architecture_comparison", "synthetic")
        return
    summary = run_synthetic_benchmark(args.architecture)
    save_summary_tables([summary], args.output_dir, f"synthetic_{args.architecture}", "synthetic")


if __name__ == "__main__":
    main()
