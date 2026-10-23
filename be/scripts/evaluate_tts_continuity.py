"""Measure TTS boundary continuity from captured WAV/event artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import wave

import numpy as np


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError(f"{path}: expected mono PCM16 WAV")
        rate = source.getframerate()
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return samples, rate


def _boundary(samples: np.ndarray, rate: int, position_ms: float) -> dict[str, float]:
    position = min(max(1, round(position_ms * rate / 1000.0)), max(1, samples.size - 1))
    window = max(1, round(rate * 0.05))
    left = samples[max(0, position - window):position]
    right = samples[position:min(samples.size, position + window)]
    left_rms = float(np.sqrt(np.mean(left * left))) if left.size else 0.0
    right_rms = float(np.sqrt(np.mean(right * right))) if right.size else 0.0
    threshold = 0.003
    left_silence = int(np.count_nonzero(np.maximum.accumulate(np.abs(left[::-1])) <= threshold)) if left.size else 0
    right_silence = int(np.count_nonzero(np.maximum.accumulate(np.abs(right)) <= threshold)) if right.size else 0
    return {
        "at_ms": position_ms,
        "jump": float(abs(samples[position] - samples[position - 1])),
        "rms_delta_db": float(20 * np.log10((right_rms + 1e-7) / (left_rms + 1e-7))),
        "silence_before_ms": left_silence / rate * 1000.0,
        "silence_after_ms": right_silence / rate * 1000.0,
    }


def _events(path: Path | None) -> dict[str, object]:
    if path is None:
        return {"sequence_errors": None, "underruns": None, "scheduled_wait_ms": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    events = payload if isinstance(payload, list) else payload.get("events", [])
    sequences = [int(item["sequence_number"]) for item in events if item.get("type") == "audio_chunk"]
    sequence_errors = sum(value != index for index, value in enumerate(sequences))
    metrics = [item for item in events if item.get("type") == "playback_metrics"]
    return {
        "sequence_errors": sequence_errors,
        "underruns": max((int(item.get("underruns", 0)) for item in metrics), default=None),
        "scheduled_wait_ms": [float(item["scheduled_wait_ms"]) for item in metrics if "scheduled_wait_ms" in item],
    }


def evaluate(manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = []
    for run in manifest["runs"]:
        wav_path = (manifest_path.parent / run["wav"]).resolve()
        samples, rate = _read_wav(wav_path)
        event_path = (manifest_path.parent / run["event_log"]).resolve() if run.get("event_log") else None
        results.append({
            "label": run["label"],
            "wav": str(wav_path),
            "sample_rate": rate,
            "duration_ms": samples.size / rate * 1000.0,
            "boundaries": [_boundary(samples, rate, value) for value in run.get("boundaries_ms", [])],
            "playback": _events(event_path),
        })
    return {"runs": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.manifest.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
