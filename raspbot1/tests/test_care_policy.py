import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT.parent / "raspbot_remote"
if str(REMOTE) not in sys.path:
    sys.path.insert(0, str(REMOTE))

from care_policy import CarePolicy, CarePolicyConfig


class TestCarePolicy(unittest.TestCase):
    def test_builds_environment_alarm_tokens(self):
        policy = CarePolicy(
            CarePolicyConfig(
                close_distance_cm=25.0,
                temp_high_c=32.0,
                temp_low_c=18.0,
                light_low_lux=50,
                light_high_lux=900,
                light_change_lux=250,
                tts_cooldown_sec=0.0,
            )
        )

        tokens = policy.build_alarm_tokens(
            env={"temp_c": 33.0, "light_lux": 40, "smoke_alarm": True},
            dist_cm=20.0,
            track=[1, 1, 1, 1],
            crying=False,
            cry_score=0,
            undervoltage=False,
            remote_alarm="",
            now=1.0,
        )

        self.assertIn("close_distance", tokens)
        self.assertIn("temp_high", tokens)
        self.assertIn("light_low", tokens)
        self.assertIn("smoke", tokens)

    def test_detects_light_change_after_baseline(self):
        policy = CarePolicy(
            CarePolicyConfig(light_change_lux=200, tts_cooldown_sec=0.0)
        )
        policy.build_alarm_tokens(
            env={"temp_c": 26.0, "light_lux": 200},
            dist_cm=60.0,
            track=[1, 1, 1, 1],
            crying=False,
            cry_score=0,
            undervoltage=False,
            remote_alarm="",
            now=1.0,
        )

        tokens = policy.build_alarm_tokens(
            env={"temp_c": 26.0, "light_lux": 500},
            dist_cm=60.0,
            track=[1, 1, 1, 1],
            crying=False,
            cry_score=0,
            undervoltage=False,
            remote_alarm="",
            now=2.0,
        )

        self.assertIn("light_changed", tokens)

    def test_baby_tts_uses_gentle_copy_and_cooldown(self):
        policy = CarePolicy(
            CarePolicyConfig(
                tts_cooldown_sec=30.0,
                tts_global_cooldown_sec=0.0,
                tts_temperature_cooldown_sec=30.0,
            )
        )

        first = policy.baby_tts_for_tokens(["temp_low"], now=10.0)
        second = policy.baby_tts_for_tokens(["temp_low"], now=20.0)
        third = policy.baby_tts_for_tokens(["temp_low"], now=45.0)

        self.assertEqual(first, "宝宝不怕，盖好小被子会暖暖的")
        self.assertEqual(second, "")
        self.assertEqual(third, "宝宝不怕，盖好小被子会暖暖的")

    def test_baby_tts_has_global_spacing_between_alarm_types(self):
        policy = CarePolicy(
            CarePolicyConfig(
                tts_cooldown_sec=30.0,
                tts_global_cooldown_sec=12.0,
                tts_temperature_cooldown_sec=180.0,
            )
        )

        first = policy.baby_tts_for_tokens(["close_distance", "temp_low"], now=10.0)
        second = policy.baby_tts_for_tokens(["temp_low"], now=15.0)
        third = policy.baby_tts_for_tokens(["temp_low"], now=30.0)
        fourth = policy.baby_tts_for_tokens(["temp_low"], now=100.0)
        fifth = policy.baby_tts_for_tokens(["temp_low"], now=220.0)

        self.assertEqual(first, "我往后一点点，给宝宝留点空间")
        self.assertEqual(second, "")
        self.assertEqual(third, "宝宝不怕，盖好小被子会暖暖的")
        self.assertEqual(fourth, "")
        self.assertEqual(fifth, "宝宝不怕，盖好小被子会暖暖的")


if __name__ == "__main__":
    unittest.main()
