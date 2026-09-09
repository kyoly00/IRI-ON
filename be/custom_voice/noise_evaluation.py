"""Manifest-driven downstream evaluation for optional noise suppression.

This benchmark evaluates the complete NS -> resampling -> VAD -> STT path. It
does not treat perceptual cleanliness as a sufficient success criterion.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import re
import statistics
from typing import Any, Iterable
import wave

import numpy as np

from .audio import AdaptiveEnergyEndpointDetector
from .config import CustomVoiceSettings
from .noise_suppression import AntiAliasResampler, AudioFrame, create_noise_suppressor
from .providers import OpenAIHttpProviders


REQUIRED_NOISE_CATEGORIES = {
    "cafe_crowd",
    "keyboard",
    "fan_air_conditioner",
    "street_noise",
    "tv",
    "background_conversation",
    "baby_crying",
    "dog_barking",
    "construction_transient",
}

EXPERIMENT_CONFIGS = {
    "no_noise_suppression": "none",
    "browser_ns": "browser",
    "browser_aec_rnnoise": "rnnoise",
    "browser_aec_deepfilternet": "deepfilternet",
}


@dataclass(frozen=True)
class CorpusItem:
    """One aligned clean/noisy utterance and its downstream labels."""

    item_id: str
    noise_type: str
    clean_wav: Path
    noisy_wav: Path
    reference_text: str
    speech_segments_ms: tuple[tuple[float, float], ...]
    entities: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()
    browser_ns_wav: Path | None = None
    browser_ns_clean_wav: Path | None = None


def load_manifest(path: Path, allow_partial_corpus: bool = False) -> list[CorpusItem]:
    """Load JSONL corpus metadata and enforce the requested noise coverage."""

    items: list[CorpusItem] = []
    base = path.resolve().parent
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        try:
            raw = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on manifest line {line_number}: {exc}") from exc

        def resolve(name: str) -> Path:
            value = Path(str(raw[name]))
            return value if value.is_absolute() else base / value

        browser_path = raw.get("browser_ns_wav")
        browser_clean_path = raw.get("browser_ns_clean_wav")
        items.append(
            CorpusItem(
                item_id=str(raw["id"]),
                noise_type=str(raw["noise_type"]),
                clean_wav=resolve("clean_wav"),
                noisy_wav=resolve("noisy_wav"),
                browser_ns_wav=(base / browser_path if browser_path and not Path(browser_path).is_absolute() else Path(browser_path))
                if browser_path
                else None,
                browser_ns_clean_wav=(
                    base / browser_clean_path
                    if browser_clean_path and not Path(browser_clean_path).is_absolute()
                    else Path(browser_clean_path)
                )
                if browser_clean_path
                else None,
                reference_text=str(raw["reference_text"]),
                speech_segments_ms=tuple((float(start), float(end)) for start, end in raw["speech_segments_ms"]),
                entities=tuple(map(str, raw.get("entities", []))),
                numbers=tuple(map(str, raw.get("numbers", []))),
            )
        )
    if not items:
        raise ValueError("Noise corpus manifest is empty")
    missing = REQUIRED_NOISE_CATEGORIES - {item.noise_type for item in items}
    if missing and not allow_partial_corpus:
        raise ValueError(f"Noise corpus is missing required categories: {', '.join(sorted(missing))}")
    return items


def _read_pcm16_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
            raise ValueError(f"Expected mono PCM16 WAV: {path}")
        return wav_file.readframes(wav_file.getnframes()), wav_file.getframerate()


def _edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, expected in enumerate(reference, start=1):
        current = [row]
        for column, actual in enumerate(hypothesis, start=1):
            current.append(
                min(current[-1] + 1, previous[column] + 1, previous[column - 1] + (expected != actual))
            )
        previous = current
    return previous[-1]


def text_metrics(reference: str, hypothesis: str, entities: Iterable[str], numbers: Iterable[str]) -> dict[str, float]:
    """Compute Korean-friendly whitespace WER, CER, entity and numeric recall."""

    ref_words = reference.split()
    hyp_words = hypothesis.split()
    ref_chars = list(re.sub(r"\s+", "", reference))
    hyp_chars = list(re.sub(r"\s+", "", hypothesis))
    normalized_hypothesis = re.sub(r"\s+", "", hypothesis).lower()

    def recall(values: Iterable[str]) -> float:
        labels = [re.sub(r"\s+", "", value).lower() for value in values]
        return sum(value in normalized_hypothesis for value in labels) / len(labels) if labels else 1.0

    return {
        "wer": _edit_distance(ref_words, hyp_words) / max(1, len(ref_words)),
        "cer": _edit_distance(ref_chars, hyp_chars) / max(1, len(ref_chars)),
        "entity_accuracy": recall(entities),
        "numeric_accuracy": recall(numbers),
    }


def vad_metrics(pcm: bytes, settings: CustomVoiceSettings, reference_segments: tuple[tuple[float, float], ...]) -> dict[str, float]:
    """Compare detector activity with frame-level reference speech labels."""

    detector = AdaptiveEnergyEndpointDetector(settings)
    frame_samples = settings.input_sample_rate * settings.input_frame_ms // 1000
    samples = np.frombuffer(pcm, dtype="<i2")
    predicted: list[bool] = []
    start_count = 0
    endpoint_count = 0
    for offset in range(0, samples.size - frame_samples + 1, frame_samples):
        events = detector.push(samples[offset : offset + frame_samples].astype("<i2").tobytes())
        start_count += sum(event.kind == "speech_start" for event in events)
        endpoint_count += sum(event.kind == "turn_end" for event in events)
        predicted.append(detector.talking or any(event.kind == "speech_start" for event in events))
    reference = []
    for index in range(len(predicted)):
        midpoint_ms = (index + 0.5) * settings.input_frame_ms
        reference.append(any(start <= midpoint_ms <= end for start, end in reference_segments))
    false_positive = sum(actual and not expected for actual, expected in zip(predicted, reference))
    false_negative = sum(not actual and expected for actual, expected in zip(predicted, reference))
    negative = sum(not value for value in reference)
    positive = sum(reference)
    expected_segments = len(reference_segments)
    return {
        "vad_false_positive_rate": false_positive / max(1, negative),
        "vad_false_negative_rate": false_negative / max(1, positive),
        "false_endpoint_rate": max(0, endpoint_count - expected_segments) / max(1, expected_segments),
        "missed_endpoint_rate": max(0, expected_segments - endpoint_count) / max(1, expected_segments),
        # In an offline corpus, a false speech-start is the measurable proxy for a false interruption.
        "false_interruption_rate": max(0, start_count - expected_segments) / max(1, expected_segments),
    }


def signal_metrics(clean_pcm: bytes, enhanced_pcm: bytes, sample_rate: int) -> dict[str, float | None]:
    """Calculate objective quality when optional PESQ/STOI packages are present."""

    clean = np.frombuffer(clean_pcm, dtype="<i2").astype(np.float32) / 32768.0
    enhanced = np.frombuffer(enhanced_pcm, dtype="<i2").astype(np.float32) / 32768.0
    length = min(clean.size, enhanced.size)
    clean, enhanced = clean[:length], enhanced[:length]
    error = clean - enhanced
    distortion_snr = 10 * np.log10((np.mean(clean * clean) + 1e-12) / (np.mean(error * error) + 1e-12))
    result: dict[str, float | None] = {"signal_snr_db": float(distortion_snr)}
    try:
        from pesq import pesq

        result["pesq"] = float(pesq(sample_rate, clean, enhanced, "wb" if sample_rate == 16_000 else "nb"))
    except (ImportError, ValueError):
        result["pesq"] = None
    try:
        from pystoi import stoi

        result["stoi"] = float(stoi(clean, enhanced, sample_rate, extended=False))
    except (ImportError, ValueError):
        result["stoi"] = None
    return result


async def _process_audio(pcm: bytes, sample_rate: int, mode: str, settings: CustomVoiceSettings) -> tuple[bytes, dict[str, Any]]:
    suppressor = create_noise_suppressor(
        mode,
        rnnoise_library=settings.rnnoise_library,
        deepfilternet_model=settings.deepfilternet_model,
    )
    resampler = AntiAliasResampler(sample_rate, settings.input_sample_rate)
    output: list[bytes] = []
    frame_samples = sample_rate * settings.transport_frame_ms // 1000
    samples = np.frombuffer(pcm, dtype="<i2")
    sample_index = 0
    try:
        for sequence, offset in enumerate(range(0, samples.size - frame_samples + 1, frame_samples)):
            frame_pcm = samples[offset : offset + frame_samples].astype("<i2").tobytes()
            frame = AudioFrame(frame_pcm, sample_rate, sequence, sample_index, offset / sample_rate)
            sample_index += frame_samples
            output.append(resampler.process(await suppressor.process(frame)).pcm)
    finally:
        await suppressor.close()
    return b"".join(output), suppressor.stats.summary()


def _mean(records: list[dict[str, Any]], key: str) -> float | None:
    values = [float(record[key]) for record in records if record.get(key) is not None]
    return round(statistics.fmean(values), 5) if values else None


async def run_noise_suppression_benchmark(
    manifest_path: Path,
    configs: list[str],
    *,
    run_stt: bool = True,
    allow_partial_corpus: bool = False,
) -> dict[str, Any]:
    """Run identical corpus items through every requested experiment config."""

    items = load_manifest(manifest_path, allow_partial_corpus)
    settings = CustomVoiceSettings.from_env()
    provider = OpenAIHttpProviders(settings) if run_stt else None
    results: dict[str, Any] = {"manifest": str(manifest_path), "configs": {}}
    try:
        for config_name in configs:
            if config_name not in EXPERIMENT_CONFIGS:
                raise ValueError(f"Unknown noise experiment config: {config_name}")
            mode = EXPERIMENT_CONFIGS[config_name]
            records: list[dict[str, Any]] = []
            for item in items:
                source_path = item.browser_ns_wav if config_name == "browser_ns" else item.noisy_wav
                if source_path is None:
                    records.append({"id": item.item_id, "noise_type": item.noise_type, "status": "missing_browser_capture"})
                    continue
                noisy_pcm, noisy_rate = _read_pcm16_wav(source_path)
                clean_pcm, clean_rate = _read_pcm16_wav(item.clean_wav)
                if noisy_rate not in {16_000, 48_000} or clean_rate not in {16_000, 48_000}:
                    raise ValueError("Noise benchmark currently supports 16 kHz or 48 kHz mono PCM16 WAV")
                enhanced, runtime = await _process_audio(noisy_pcm, noisy_rate, mode if config_name != "browser_ns" else "browser", settings)
                clean_16k, _ = await _process_audio(clean_pcm, clean_rate, "none", settings)
                if config_name == "browser_ns" and item.browser_ns_clean_wav is not None:
                    browser_clean_pcm, browser_clean_rate = _read_pcm16_wav(item.browser_ns_clean_wav)
                    clean_processed, _ = await _process_audio(browser_clean_pcm, browser_clean_rate, "none", settings)
                elif config_name == "browser_ns":
                    clean_processed = None
                else:
                    clean_processed, _ = await _process_audio(clean_pcm, clean_rate, mode, settings)
                hypothesis = await provider.transcribe(enhanced) if provider else ""
                quality = signal_metrics(clean_16k, enhanced, settings.input_sample_rate)
                clean_distortion = (
                    signal_metrics(clean_16k, clean_processed, settings.input_sample_rate)["signal_snr_db"]
                    if clean_processed is not None
                    else None
                )
                record: dict[str, Any] = {
                    "id": item.item_id,
                    "noise_type": item.noise_type,
                    "status": "ok",
                    "transcript": hypothesis if run_stt else None,
                    **runtime,
                    **vad_metrics(enhanced, settings, item.speech_segments_ms),
                    **quality,
                    "clean_speech_distortion_snr_db": clean_distortion,
                }
                if config_name == "browser_ns":
                    # Browser built-in DSP cost is outside the Python process and cannot be
                    # inferred from a preprocessed WAV. Keep it unknown instead of reporting 0.
                    record["processing_latency_ms_mean"] = None
                    record["realtime_factor"] = None
                    record["cpu_usage_pct_during_processing"] = None
                    record["runtime_cost_scope"] = "not_observable_from_offline_browser_capture"
                if run_stt:
                    record.update(text_metrics(item.reference_text, hypothesis, item.entities, item.numbers))
                records.append(record)
            completed = [record for record in records if record["status"] == "ok"]
            metric_names = [
                "wer", "cer", "entity_accuracy", "numeric_accuracy",
                "vad_false_positive_rate", "vad_false_negative_rate", "pesq", "stoi",
                "false_endpoint_rate", "missed_endpoint_rate", "false_interruption_rate",
                "processing_latency_ms_mean", "realtime_factor", "cpu_usage_pct_during_processing",
                "clean_speech_distortion_snr_db",
            ]
            results["configs"][config_name] = {
                "summary": {name: _mean(completed, name) for name in metric_names},
                "items": records,
            }
    finally:
        if provider is not None:
            await provider.close()
    return results


def print_noise_summary(results: dict[str, Any]) -> None:
    """Print downstream quality and runtime cost side-by-side."""

    print("\nNoise suppression downstream benchmark")
    print("=" * 132)
    print(
        f"{'Configuration':<32} {'WER':>7} {'CER':>7} {'Entity':>8} {'Number':>8} "
        f"{'VAD FP':>8} {'VAD FN':>8} {'PESQ':>7} {'STOI':>7} {'NS ms':>8} {'RTF':>7} {'CPU%':>7} {'Clean SNR':>10}"
    )
    print("-" * 132)
    for name, config in results["configs"].items():
        summary = config["summary"]

        def value(key: str, width: int = 7) -> str:
            raw = summary.get(key)
            return f"{raw:.3f}" if raw is not None else "-"

        print(
            f"{name:<32} {value('wer'):>7} {value('cer'):>7} {value('entity_accuracy'):>8} "
            f"{value('numeric_accuracy'):>8} {value('vad_false_positive_rate'):>8} "
            f"{value('vad_false_negative_rate'):>8} {value('pesq'):>7} {value('stoi'):>7} "
            f"{value('processing_latency_ms_mean'):>8} {value('realtime_factor'):>7} "
            f"{value('cpu_usage_pct_during_processing'):>7} {value('clean_speech_distortion_snr_db'):>10}"
        )
