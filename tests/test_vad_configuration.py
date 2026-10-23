"""VAD 시작 threshold 기본값과 진단 계약 회귀 테스트."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "be"))

from custom_voice.config import CustomVoiceSettings  # noqa: E402
from custom_voice.silero_vad import SileroVADDetector  # noqa: E402


class _RecordingSession:
    def __init__(self) -> None:
        self.inputs: list[dict[str, np.ndarray]] = []

    def run(self, _outputs, inputs):
        self.inputs.append(inputs)
        return [np.array([[0.9]], dtype=np.float32), np.zeros((2, 1, 128), dtype=np.float32)]


class VADConfigurationTests(unittest.TestCase):
    def test_default_threshold_matches_environment_default(self) -> None:
        self.assertEqual(CustomVoiceSettings().vad_threshold, 0.25)

    def test_silero_keeps_official_64_sample_streaming_context(self) -> None:
        session = _RecordingSession()
        with patch("onnxruntime.InferenceSession", return_value=session):
            detector = SileroVADDetector(CustomVoiceSettings())
        detector.push(np.full(512, 1_000, dtype="<i2").tobytes())
        detector.push(np.full(512, 2_000, dtype="<i2").tobytes())

        self.assertEqual(session.inputs[0]["input"].shape, (1, 576))
        np.testing.assert_allclose(session.inputs[0]["input"][0, :64], 0.0)
        np.testing.assert_allclose(session.inputs[1]["input"][0, :64], 1_000 / 32768.0)


if __name__ == "__main__":
    unittest.main()
