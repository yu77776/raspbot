import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.baby_filter import TrackResult, TrackState
from pc_modules.motion_controller import MotionConfig, MotionController, MotionState


class TestMotionLightSafety(unittest.TestCase):
    def test_light_alarm_keeps_servo_tracking_but_stops_body_motion(self):
        controller = MotionController(
            MotionConfig(enable_motor_control=True, body_dead_zone=1.0),
            tuning_path=None,
        )
        track = TrackResult(
            state=TrackState.LOCKED,
            box=[500.0, 180.0, 620.0, 340.0],
            conf=0.9,
        )

        out = controller.update(
            track,
            {"dist_cm": 60.0, "alarm": "light_low"},
            dt=0.1,
        )

        self.assertNotEqual(out.servo_x, 90.0)
        self.assertEqual(out.action, "stop")
        self.assertEqual(out.left_speed, 0)
        self.assertEqual(out.right_speed, 0)

    def test_scan_timeout_returns_to_idle(self):
        controller = MotionController(
            MotionConfig(scan_timeout=1.0),
            tuning_path="",
        )
        controller.state = MotionState.SCAN
        controller._scan_start_t = 10.0

        with patch("pc_modules.motion_controller.time.monotonic", return_value=12.0):
            out = controller.update(
                TrackResult(state=TrackState.NONE),
                {"dist_cm": 60.0, "alarm": ""},
                dt=0.1,
            )

        self.assertEqual(controller.state, MotionState.IDLE)
        self.assertEqual(out.state, MotionState.IDLE)
        self.assertEqual(out.action, "stop")


if __name__ == "__main__":
    unittest.main()
