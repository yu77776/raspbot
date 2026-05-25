import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT.parent / "raspbot_remote"
if str(REMOTE) not in sys.path:
    sys.path.insert(0, str(REMOTE))

from protocol import (
    EnvPacket,
    ImuPacket,
    cliff_direction,
    cliff_level,
    is_cliff_track,
)
from care_policy import CarePolicy, CarePolicyConfig, CliffDetector


class TestCliffLevel(unittest.TestCase):
    def test_safe_all_ground(self):
        self.assertEqual(cliff_level([1, 1, 1, 1]), 0)

    def test_safe_one_dark(self):
        self.assertEqual(cliff_level([0, 1, 1, 1]), 0)
        self.assertEqual(cliff_level([1, 0, 1, 1]), 0)

    def test_warning_two_dark(self):
        self.assertEqual(cliff_level([0, 0, 1, 1]), 1)
        self.assertEqual(cliff_level([0, 1, 1, 0]), 1)

    def test_warning_front_both_dark(self):
        # Front two dark even if rear are ground
        self.assertEqual(cliff_level([0, 0, 1, 1]), 1)

    def test_danger_three_dark(self):
        self.assertEqual(cliff_level([0, 0, 0, 1]), 2)
        self.assertEqual(cliff_level([1, 0, 0, 0]), 2)

    def test_cliff_all_dark(self):
        self.assertEqual(cliff_level([0, 0, 0, 0]), 3)

    def test_bad_input_returns_safe(self):
        self.assertEqual(cliff_level(None), 0)
        self.assertEqual(cliff_level([]), 0)
        self.assertEqual(cliff_level("abc"), 0)
        self.assertEqual(cliff_level([1, 1]), 0)  # too short

    def test_string_values(self):
        self.assertEqual(cliff_level(["0", "0", "0", "0"]), 3)
        self.assertEqual(cliff_level([0, "0", 1, 1]), 1)


class TestIsCliffTrack(unittest.TestCase):
    def test_backward_compat(self):
        self.assertFalse(is_cliff_track([1, 1, 1, 1]))
        self.assertFalse(is_cliff_track([0, 0, 0, 1]))
        self.assertTrue(is_cliff_track([0, 0, 0, 0]))


class TestCliffDirection(unittest.TestCase):
    def test_nose_down_forward_danger(self):
        self.assertEqual(cliff_direction(-15.0, 0.0, True), "forward")
        self.assertEqual(cliff_direction(-8.5, 2.0, True), "forward")

    def test_nose_up_rear_danger(self):
        self.assertEqual(cliff_direction(15.0, 0.0, True), "rear")
        self.assertEqual(cliff_direction(8.5, -2.0, True), "rear")

    def test_side_tilt(self):
        self.assertEqual(cliff_direction(0.0, 15.0, True), "side")
        self.assertEqual(cliff_direction(5.0, 12.0, True), "side")  # roll dominates

    def test_suspended_level(self):
        self.assertEqual(cliff_direction(0.0, 0.0, True), "suspended")
        self.assertEqual(cliff_direction(-5.0, 3.0, True), "suspended")

    def test_imu_unhealthy_fallback(self):
        # When IMU is unhealthy, returns "suspended" (stop — safest when uncertain)
        self.assertEqual(cliff_direction(15.0, 0.0, False), "suspended")
        self.assertEqual(cliff_direction(-15.0, 0.0, False), "suspended")
        self.assertEqual(cliff_direction(0.0, 0.0, False), "suspended")

    def test_custom_thresholds(self):
        self.assertEqual(
            cliff_direction(-5.0, 0.0, True, pitch_down_deg=-4.0),
            "forward",
        )
        self.assertEqual(
            cliff_direction(5.0, 0.0, True, pitch_up_deg=4.0),
            "rear",
        )


def _imu(healthy=True, pitch=0.0, roll=0.0):
    return ImuPacket(pitch=pitch, roll=roll, healthy=healthy, calibrated=True)


class TestCliffDetector(unittest.TestCase):
    def setUp(self):
        self.detector = CliffDetector(confirm_samples=2, clear_samples=5)

    def test_initial_state_safe(self):
        self.assertEqual(self.detector.level, 0)
        self.assertEqual(self.detector.direction, "")

    def test_single_spike_does_not_trigger(self):
        # One sample of cliff → stays safe (debounce)
        level, direction = self.detector.update([0, 0, 0, 0])
        self.assertEqual(level, 0)
        self.assertEqual(direction, "")

    def test_two_confirm_triggers_warning(self):
        self.detector.update([0, 0, 1, 1])  # level 1, first sample
        level, direction = self.detector.update([0, 0, 1, 1])  # level 1, second → confirm
        self.assertEqual(level, 1)

    def test_two_confirm_triggers_cliff(self):
        self.detector.update([0, 0, 0, 0])  # level 3
        level, _ = self.detector.update([0, 0, 0, 0])  # level 3 → confirm
        self.assertEqual(level, 3)

    def test_escalation_path(self):
        # 0 → 1 → 2 → 3
        for _ in range(2):
            self.detector.update([0, 0, 1, 1])
        self.assertEqual(self.detector.level, 1)

        for _ in range(2):
            self.detector.update([0, 0, 0, 1])
        self.assertEqual(self.detector.level, 2)

        for _ in range(2):
            self.detector.update([0, 0, 0, 0])
        self.assertEqual(self.detector.level, 3)

    def test_clearing_requires_many_safe_samples(self):
        # Get to cliff state
        for _ in range(2):
            self.detector.update([0, 0, 0, 0])
        self.assertEqual(self.detector.level, 3)

        # 4 safe samples → not enough to clear
        for _ in range(4):
            level, _ = self.detector.update([1, 1, 1, 1])
            self.assertEqual(level, 3)  # still cliff

        # 5th safe sample → clear
        level, _ = self.detector.update([1, 1, 1, 1])
        self.assertEqual(level, 0)

    def test_direction_with_imu(self):
        for _ in range(2):
            self.detector.update([0, 0, 0, 0], imu_packet=_imu(pitch=-15.0))
        self.assertEqual(self.detector.direction, "forward")

        # Clear first
        self.detector._level = 0
        self.detector._level_up_count = 0
        self.detector._level_down_count = 0

        for _ in range(2):
            self.detector.update([0, 0, 0, 0], imu_packet=_imu(pitch=15.0))
        self.assertEqual(self.detector.direction, "rear")

    def test_direction_without_imu_fallback(self):
        for _ in range(2):
            self.detector.update([0, 0, 0, 0], imu_packet=None)
        self.assertEqual(self.detector.level, 3)
        self.assertEqual(self.detector.direction, "suspended")

    def test_direction_empty_when_safe(self):
        self.detector.update([1, 1, 1, 1])
        self.assertEqual(self.detector.direction, "")

    def test_interrupted_escalation_resets_count(self):
        # One cliff sample, then safe → count resets
        self.detector.update([0, 0, 0, 0])
        self.detector.update([1, 1, 1, 1])
        self.assertEqual(self.detector.level, 0)

        # Need 2 fresh samples again
        self.detector.update([0, 0, 0, 0])
        self.assertEqual(self.detector.level, 0)
        self.detector.update([0, 0, 0, 0])
        self.assertEqual(self.detector.level, 3)


class TestCarePolicyCliffIntegration(unittest.TestCase):
    def setUp(self):
        self.policy = CarePolicy(CarePolicyConfig(tts_cooldown_sec=0.0))

    def test_cliff_token_only_at_level_3(self):
        # Level 1-2 should NOT generate cliff token
        for _ in range(2):
            self.policy.build_alarm_tokens(
                env={},
                dist_cm=80.0,
                track=[0, 0, 1, 1],
                crying=False,
                cry_score=0,
                undervoltage=False,
                remote_alarm="",
                now=1.0,
            )
        self.assertNotIn("cliff", self.policy.build_alarm_tokens(
            env={}, dist_cm=80.0, track=[0, 0, 1, 1],
            crying=False, cry_score=0, undervoltage=False,
            remote_alarm="", now=2.0,
        ))

    def test_cliff_token_at_level_3(self):
        for _ in range(2):
            self.policy.build_alarm_tokens(
                env={},
                dist_cm=80.0,
                track=[0, 0, 0, 0],
                crying=False,
                cry_score=0,
                undervoltage=False,
                remote_alarm="",
                now=1.0,
            )
        tokens = self.policy.build_alarm_tokens(
            env={}, dist_cm=80.0, track=[0, 0, 0, 0],
            crying=False, cry_score=0, undervoltage=False,
            remote_alarm="", now=2.0,
        )
        self.assertIn("cliff", tokens)

    def test_cliff_level_property(self):
        for _ in range(2):
            self.policy.build_alarm_tokens(
                env={},
                dist_cm=80.0,
                track=[0, 0, 0, 0],
                crying=False,
                cry_score=0,
                undervoltage=False,
                remote_alarm="",
                now=1.0,
            )
        self.assertEqual(self.policy.cliff_level, 3)
        self.assertEqual(self.policy.cliff_direction, "suspended")  # no IMU → stop

    def test_imu_affects_direction(self):
        imu = _imu(pitch=15.0)  # nose up → rear danger
        for _ in range(2):
            self.policy.build_alarm_tokens(
                env={},
                dist_cm=80.0,
                track=[0, 0, 0, 0],
                crying=False,
                cry_score=0,
                undervoltage=False,
                remote_alarm="",
                now=1.0,
                imu=imu,
            )
        self.assertEqual(self.policy.cliff_level, 3)
        self.assertEqual(self.policy.cliff_direction, "rear")

    def test_old_signature_still_works(self):
        # build_alarm_tokens without imu parameter (backward compat)
        tokens = self.policy.build_alarm_tokens(
            env={},
            dist_cm=80.0,
            track=[1, 1, 1, 1],
            crying=False,
            cry_score=0,
            undervoltage=False,
            remote_alarm="",
            now=1.0,
        )
        self.assertIsInstance(tokens, list)


class TestEnvPacketCliffFields(unittest.TestCase):
    def test_new_fields_in_to_dict(self):
        packet = EnvPacket(
            light=0, light_lux=0, temp_raw=0, temp_c=0.0,
            smoke=0, volume=0, crying=False, cry_score=0,
            dist_cm=999.0, track=[1, 1, 1, 1], alarm="",
            imu=None, fps=0,
            cliff_level=2, cliff_direction="forward",
        )
        data = packet.to_dict()
        self.assertEqual(data["cliff_level"], 2)
        self.assertEqual(data["cliff_direction"], "forward")

    def test_default_values(self):
        packet = EnvPacket(
            light=0, light_lux=0, temp_raw=0, temp_c=0.0,
            smoke=0, volume=0, crying=False, cry_score=0,
            dist_cm=999.0, track=[1, 1, 1, 1], alarm="",
            imu=None, fps=0,
        )
        self.assertEqual(packet.cliff_level, 0)
        self.assertEqual(packet.cliff_direction, "")

    def test_cliff_level_normalized_to_int(self):
        packet = EnvPacket(
            light=0, light_lux=0, temp_raw=0, temp_c=0.0,
            smoke=0, volume=0, crying=False, cry_score=0,
            dist_cm=999.0, track=[1, 1, 1, 1], alarm="",
            imu=None, fps=0,
            cliff_level="3",  # string should be normalized
        )
        self.assertEqual(packet.cliff_level, 3)
        self.assertIsInstance(packet.cliff_level, int)


if __name__ == "__main__":
    unittest.main()
