import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT.parent / "raspbot_remote"
if str(REMOTE) not in sys.path:
    sys.path.insert(0, str(REMOTE))

from protocol import EnvPacket


class TestEnvPacket(unittest.TestCase):
    def test_serializes_battery_status_without_fake_percent(self):
        packet = EnvPacket(
            light=0,
            light_lux=0,
            temp_raw=233,
            temp_c=23.7,
            smoke=0,
            volume=80,
            crying=False,
            cry_score=0,
            dist_cm=42.0,
            track=[1, 1, 1, 1],
            alarm="",
            imu=None,
            fps=12,
            battery_status="LOW",
        )

        data = packet.to_dict()

        self.assertNotIn("battery_percent", data)
        self.assertEqual(data["battery_status"], "LOW")
        self.assertTrue(data["pcf8591_ok"])

    def test_normalizes_track(self):
        packet = EnvPacket(
            light=0,
            light_lux=0,
            temp_raw=0,
            temp_c=0.0,
            smoke=0,
            volume=0,
            crying=False,
            cry_score=0,
            dist_cm=999.0,
            track=[1, "0", "bad"],
            alarm="",
            imu=None,
            fps=0,
        )

        self.assertEqual(packet.to_dict()["track"], [1, 1, 1, 1])


if __name__ == "__main__":
    unittest.main()
