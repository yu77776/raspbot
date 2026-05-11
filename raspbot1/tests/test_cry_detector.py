import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.cry_detector import CryDetectorConfig, CryStateSmoother


class TestCryStateSmoother(unittest.TestCase):
    def test_requires_sustained_score_before_triggering(self):
        smoother = CryStateSmoother(
            CryDetectorConfig(
                trigger_score=0.60,
                release_score=0.40,
                trigger_sec=1.0,
                release_sec=1.0,
                hop_sec=0.5,
            )
        )

        first = smoother.update(0.8)
        second = smoother.update(0.8)

        self.assertFalse(first.crying)
        self.assertTrue(second.crying)
        self.assertEqual(second.score, 80)

    def test_hysteresis_requires_sustained_low_score_before_clearing(self):
        smoother = CryStateSmoother(
            CryDetectorConfig(
                trigger_score=0.60,
                release_score=0.40,
                trigger_sec=0.5,
                release_sec=1.0,
                hop_sec=0.5,
            )
        )

        self.assertTrue(smoother.update(0.9).crying)
        still_on = smoother.update(0.2)
        cleared = smoother.update(0.2)

        self.assertTrue(still_on.crying)
        self.assertFalse(cleared.crying)


if __name__ == "__main__":
    unittest.main()
