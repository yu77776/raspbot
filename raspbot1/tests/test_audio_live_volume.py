import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT.parent / "raspbot_remote"
if str(REMOTE) not in sys.path:
    sys.path.insert(0, str(REMOTE))

from modules.audio import Audio


class FakeMusic:
    """Minimal stand-in for pygame.mixer.music that records volume calls."""

    def __init__(self, busy_ticks):
        self._busy_remaining = busy_ticks
        self.volume_calls = []
        self.stopped = False

    def get_busy(self):
        if self._busy_remaining <= 0:
            return False
        self._busy_remaining -= 1
        return True

    def set_volume(self, v):
        self.volume_calls.append(round(v, 4))

    def stop(self):
        self.stopped = True


class FakePygame:
    def __init__(self, music):
        self.mixer = type("M", (), {"music": music})()


class TestAudioLiveVolume(unittest.TestCase):
    def test_volume_change_during_playback_applies_to_current_track(self):
        """Changing volume mid-playback must converge the *current* track,
        not just take effect on the next one."""
        audio = Audio()
        audio.volume = 80
        music = FakeMusic(busy_ticks=5)

        tick = {"n": 0}
        real_sleep = None

        def fake_sleep(_):
            # Simulate the App raising volume to 30 after the 2nd poll tick.
            tick["n"] += 1
            if tick["n"] == 2:
                with audio.lock:
                    audio.volume = 30

        with patch("modules.audio.pygame", FakePygame(music)), \
             patch("modules.audio.time.sleep", side_effect=fake_sleep):
            audio._wait_until_finished()

        # The new volume (0.30) must have been pushed to the playing stream.
        self.assertIn(0.30, music.volume_calls)
        # And the last applied volume should be the new one, not the old 0.80.
        self.assertEqual(music.volume_calls[-1], 0.30)

    def test_stop_flag_halts_playback(self):
        audio = Audio()
        audio.volume = 50
        music = FakeMusic(busy_ticks=10)
        audio.stop_flag.set()

        with patch("modules.audio.pygame", FakePygame(music)), \
             patch("modules.audio.time.sleep", side_effect=lambda _: None):
            audio._wait_until_finished()

        self.assertTrue(music.stopped)


if __name__ == "__main__":
    unittest.main()
