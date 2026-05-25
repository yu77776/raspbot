import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT.parent / "raspbot_remote"
if str(REMOTE) not in sys.path:
    sys.path.insert(0, str(REMOTE))

from env_sampler import EnvSampler


class FakePcf:
    def __init__(self, volume=20, pcf8591_ok=True):
        self.volume = volume
        self.pcf8591_ok = pcf8591_ok

    def get_data(self):
        return {
            "light": 0,
            "light_lux": 0,
            "temp_raw": 0,
            "temp_c": 24.0,
            "smoke": 0,
            "volume": self.volume,
            "pcf8591_ok": self.pcf8591_ok,
        }


class FakeAudio:
    def __init__(self):
        self.volume = 100
        self.calls = []

    def set_volume(self, volume):
        self.volume = int(volume)
        self.calls.append(int(volume))


class FakeUltrasonic:
    def get_distance(self):
        return 80.0


class FakeInfrared:
    def get_data(self):
        return {"track": [1, 1, 1, 1]}


class FakeImu:
    enabled = False


class FakeCamera:
    def get_fps(self):
        return 0


class TestEnvSamplerVolume(unittest.TestCase):
    @patch("env_sampler._check_undervoltage", return_value=False)
    def test_app_volume_holds_until_knob_actually_moves(self, _):
        pcf = FakePcf(volume=20)
        audio = FakeAudio()
        knob_events = []
        sampler = EnvSampler(
            pcf,
            FakeUltrasonic(),
            FakeInfrared(),
            FakeImu(),
            FakeCamera(),
            audio,
            cry_alarm_score_min=60,
            remote_cry_provider=lambda: (None, None, None),
            knob_volume_deadband=3,
            knob_volume_after_app_grace_sec=0.0,
            knob_volume_callback=knob_events.append,
        )

        sampler.sample()
        sampler.note_app_audio_volume(80)
        audio.set_volume(80)
        sampler.sample()
        pcf.volume = 22
        sampler.sample()
        pcf.volume = 40
        sampler.sample()

        self.assertEqual(audio.calls, [20, 80, 40])
        self.assertEqual(knob_events, [20, 40])

    @patch("env_sampler._check_undervoltage", return_value=False)
    def test_app_volume_holds_during_grace_even_if_knob_value_differs(self, _):
        pcf = FakePcf(volume=20)
        audio = FakeAudio()
        sampler = EnvSampler(
            pcf,
            FakeUltrasonic(),
            FakeInfrared(),
            FakeImu(),
            FakeCamera(),
            audio,
            cry_alarm_score_min=60,
            remote_cry_provider=lambda: (None, None, None),
            knob_volume_deadband=3,
            knob_volume_after_app_grace_sec=60.0,
        )

        sampler.sample()
        sampler.note_app_audio_volume(80)
        audio.set_volume(80)
        pcf.volume = 40
        sampler.sample()

        self.assertEqual(audio.volume, 80)
        self.assertEqual(audio.calls, [20, 80])

    @patch("env_sampler._check_undervoltage", return_value=False)
    def test_unhealthy_pcf_does_not_apply_knob_volume(self, _):
        pcf = FakePcf(volume=0, pcf8591_ok=False)
        audio = FakeAudio()
        sampler = EnvSampler(
            pcf,
            FakeUltrasonic(),
            FakeInfrared(),
            FakeImu(),
            FakeCamera(),
            audio,
            cry_alarm_score_min=60,
            remote_cry_provider=lambda: (None, None, None),
        )

        packet = sampler.sample()

        self.assertEqual(audio.calls, [])
        self.assertEqual(audio.volume, 100)
        self.assertFalse(packet.pcf8591_ok)


if __name__ == "__main__":
    unittest.main()
