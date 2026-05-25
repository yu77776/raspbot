import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.protocol import PLAY_SONG_NEXT
from pc_modules.voice_cry_bridge import parse_voice_intent


class TestVoiceIntent(unittest.TestCase):
    def test_play_song_accepts_colloquial_phrase(self):
        intent = parse_voice_intent("放首歌。")

        self.assertIsNotNone(intent)
        self.assertEqual(intent["action"], "stop")
        self.assertEqual(intent["play_song"], "default")
        self.assertIsNone(intent["audio_volume"])
        self.assertFalse(intent["stop_audio"])

    def test_next_song_still_uses_playlist_sentinel(self):
        intent = parse_voice_intent("下一首")

        self.assertIsNotNone(intent)
        self.assertEqual(intent["play_song"], PLAY_SONG_NEXT)
        self.assertIsNone(intent["audio_volume"])

    def test_volume_up_voice_intent_sets_audio_volume(self):
        intent = parse_voice_intent("声音大点")

        self.assertIsNotNone(intent)
        self.assertEqual(intent["action"], "stop")
        self.assertEqual(intent["audio_volume"], 80)

    def test_volume_down_voice_intent_sets_audio_volume(self):
        intent = parse_voice_intent("小声一点")

        self.assertIsNotNone(intent)
        self.assertEqual(intent["action"], "stop")
        self.assertEqual(intent["audio_volume"], 40)


if __name__ == "__main__":
    unittest.main()
