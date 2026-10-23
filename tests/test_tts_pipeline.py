import sys
from pathlib import Path
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "be"))

from custom_voice.tts_pipeline import (  # noqa: E402
    TTSChunkPolicy,
    TTSChunkScheduler,
    inspect_pcm_boundary,
    stitch_pcm_boundary,
)


class TTSChunkSchedulerTests(unittest.TestCase):
    def test_prefers_complete_sentence_over_character_threshold(self):
        scheduler = TTSChunkScheduler(TTSChunkPolicy(10, 20, 80, 500))
        chunks = scheduler.feed("이 문장은 자연스럽게 끝납니다. 다음 문장")
        self.assertEqual([chunk.text for chunk in chunks], ["이 문장은 자연스럽게 끝납니다."])
        self.assertEqual(chunks[0].boundary, "sentence")

    def test_latency_uses_available_whitespace(self):
        scheduler = TTSChunkScheduler(TTSChunkPolicy(24, 64, 180, 500))
        scheduler.feed("아직 문장이 끝나지 않았지만 자연스러운 단위가 있습니다", now=1.0)
        chunk = scheduler.flush_due(now=1.6)
        self.assertIsNotNone(chunk)
        self.assertTrue(chunk.boundary.startswith("latency_"))
        self.assertFalse(chunk.text.endswith(" "))

    def test_maximum_length_is_safety_boundary(self):
        scheduler = TTSChunkScheduler(TTSChunkPolicy(4, 8, 12, 500))
        chunks = scheduler.feed("가" * 13, now=1.0)
        self.assertEqual(len(chunks[0].text), 12)
        self.assertEqual(chunks[0].boundary, "maximum_hard")

    def test_sentence_beyond_maximum_does_not_bypass_safety_limit(self):
        scheduler = TTSChunkScheduler(TTSChunkPolicy(4, 8, 12, 500))
        chunks = scheduler.feed("가" * 20 + ".", now=1.0)
        self.assertEqual(len(chunks[0].text), 12)

    def test_tiny_first_chunk_waits_without_zero_deadline_loop(self):
        scheduler = TTSChunkScheduler(
            TTSChunkPolicy(first_min_chars=12, first_maximum_latency_ms=380)
        )
        scheduler.feed("네.", now=1.0)

        self.assertIsNone(scheduler.flush_due(now=1.4))
        self.assertGreater(scheduler.seconds_until_deadline(now=1.4), 0)

    def test_tiny_korean_clause_is_not_emitted_as_first_chunk(self):
        scheduler = TTSChunkScheduler(
            TTSChunkPolicy(first_min_chars=12, first_maximum_latency_ms=380)
        )
        scheduler.feed("넣고 ", now=1.0)

        self.assertIsNone(scheduler.flush_due(now=1.4))


class PCMBoundaryTests(unittest.TestCase):
    def test_detects_and_crossfades_large_jump(self):
        previous = np.full(240, 20_000, dtype="<i2").tobytes()
        current = np.full(240, -20_000, dtype="<i2").tobytes()
        metrics = inspect_pcm_boundary(previous, current, 24_000)
        stitched, _, applied = stitch_pcm_boundary(previous, current, 24_000)
        self.assertGreater(metrics.jump, 1.0)
        self.assertTrue(applied)
        self.assertLess(len(stitched), len(previous) + len(current))


if __name__ == "__main__":
    unittest.main()
