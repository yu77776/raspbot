import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.baby_filter import _iou


class TestBabyFilterGeometry(unittest.TestCase):
    def test_iou_returns_zero_for_zero_area_boxes(self):
        self.assertEqual(_iou([0, 0, 0, 10], [0, 0, 10, 10]), 0.0)
        self.assertEqual(_iou([0, 0, 10, 10], [5, 5, 5, 12]), 0.0)


if __name__ == "__main__":
    unittest.main()
