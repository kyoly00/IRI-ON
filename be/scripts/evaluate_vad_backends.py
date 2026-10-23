"""Feed one 16 kHz PCM WAV to Silero and MarbleNet and report measured decisions."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import time
import wave

from be.custom_voice.config import CustomVoiceSettings
from be.custom_voice.silero_vad import create_vad_detector


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as source:
        if source.getframerate() != 16_000 or source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("input must be 16 kHz mono PCM16 WAV")
        return source.readframes(source.getnframes())


def evaluate(detector, pcm: bytes, frame_ms: int = 20) -> dict[str, object]:
    frame_bytes = 16_000 * 2 * frame_ms // 1000
    events = []
    probabilities = []
    started = time.perf_counter()
    for offset in range(0, len(pcm), frame_bytes):
        chunk = pcm[offset:offset + frame_bytes]
        for event in detector.push(chunk):
            events.append({"kind": event.kind, "at_ms": offset / 32.0, "duration_ms": event.duration_ms})
        probability = getattr(detector, "last_probability", None)
        if probability is not None:
            probabilities.append(float(probability))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "detector": type(detector).__name__,
        "events": events,
        "probability_frames": len(probabilities),
        "mean_probability": sum(probabilities) / len(probabilities) if probabilities else None,
        "max_probability": max(probabilities) if probabilities else None,
        "processing_ms": elapsed_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", type=Path)
    args = parser.parse_args()
    pcm = read_pcm(args.wav)
    base = CustomVoiceSettings()
    results = {}
    for name in ("silero", "marblenet"):
        settings = replace(base, vad_backend=name, vad_mode=name)
        detector = create_vad_detector(settings)
        results[name] = evaluate(detector, pcm)
    print(json.dumps({"input": str(args.wav.resolve()), "results": results}, indent=2))


if __name__ == "__main__":
    main()
