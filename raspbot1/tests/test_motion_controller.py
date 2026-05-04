import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.baby_filter import TrackState
from pc_modules.motion_controller import MotionConfig, MotionController


def locked_box(box):
    return SimpleNamespace(state=TrackState.LOCKED, box=box)


def env():
    return {"dist_cm": 1000, "imu": {"yaw": 0}}


class MotionControllerTest(unittest.TestCase):
    def test_servo_continues_tracking_left_and_right_targets(self):
        cfg = MotionConfig(
            enable_motor_control=True,
            enable_distance_follow=False,
            servo_kp_x=0.08,
            servo_kd_x=0.0,
            body_dead_zone=12.0,
        )

        left = MotionController(config=cfg, tuning_path="")
        left_1 = left.update(locked_box((0, 180, 80, 300)), env(), 1 / 12)
        left_2 = left.update(locked_box((0, 180, 80, 300)), env(), 1 / 12)

        right = MotionController(config=cfg, tuning_path="")
        right_1 = right.update(locked_box((560, 180, 640, 300)), env(), 1 / 12)
        right_2 = right.update(locked_box((560, 180, 640, 300)), env(), 1 / 12)

        self.assertGreater(left_1.servo_x, 90)
        self.assertGreater(left_2.servo_x, left_1.servo_x)
        self.assertLess(right_1.servo_x, 90)
        self.assertLess(right_2.servo_x, right_1.servo_x)

    def test_servo_pid_output_is_not_software_limited(self):
        cfg = MotionConfig(
            enable_motor_control=False,
            servo_kp_x=0.1,
            servo_kd_x=0.0,
        )
        controller = MotionController(config=cfg, tuning_path="")

        out = controller.update(locked_box((0, 180, 80, 300)), env(), 1 / 12)

        self.assertGreater(out.servo_x, 100)

    def test_body_pid_keeps_spinning_without_tick_throttle(self):
        cfg = MotionConfig(
            enable_motor_control=True,
            enable_distance_follow=False,
            servo_kp_x=0.0,
            servo_kd_x=0.0,
            body_dead_zone=5.0,
            body_speed_min=20,
            body_speed_max=40,
        )
        controller = MotionController(config=cfg, tuning_path="")
        controller.servo_x = 45.0

        actions = [
            controller.update(locked_box((300, 180, 340, 300)), env(), 1 / 12).action
            for _ in range(6)
        ]

        self.assertEqual(actions, ["spin_right"] * 6)

    def test_scan_starts_from_current_pan_side(self):
        cfg = MotionConfig(scan_speed_deg_s=60.0, scan_range_min=70.0, scan_range_max=110.0)
        controller = MotionController(config=cfg, tuning_path="")

        controller.servo_x = 130.0
        controller._enter_scan()
        values = [controller._do_scan(0.2).servo_x for _ in range(10)]

        self.assertEqual(values[0], 110.0)
        self.assertLessEqual(min(values), 70)
        self.assertGreaterEqual(max(values), 110)


if __name__ == "__main__":
    unittest.main()
