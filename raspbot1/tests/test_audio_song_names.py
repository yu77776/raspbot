import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT.parent / "raspbot_remote"
if str(REMOTE) not in sys.path:
    sys.path.insert(0, str(REMOTE))

from modules.audio import Audio
from protocol import PLAY_SONG_NEXT


class TestAudioSongNames(unittest.TestCase):
    def test_utf8_filename_display_name_survives_gb18030_filesystem_decode(self):
        audio = Audio()
        raw_name = "稻香-周杰伦.mp3"
        gb18030_view = raw_name.encode("utf-8").decode("gb18030", errors="surrogateescape")
        audio._playlist = [gb18030_view]
        audio._display_names = {gb18030_view: audio._display_name_for_entry(gb18030_view)}

        self.assertEqual(audio.enqueue_song(PLAY_SONG_NEXT), raw_name)
        self.assertEqual(audio.resolve_song(raw_name), gb18030_view)

    def test_tts_enqueue_prefetches_before_playback_queue(self):
        audio = Audio()
        started = []

        class FakeThread:
            def __init__(self, target, args=(), daemon=False):
                self.target = target
                self.args = args
                self.daemon = daemon

            def start(self):
                started.append((self.target, self.args, self.daemon))

        with patch("modules.audio.threading.Thread", FakeThread):
            audio.enqueue("tts", "宝宝别着急")

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][0].__self__, audio)
        self.assertEqual(started[0][0].__func__, audio._prefetch_tts.__func__)
        self.assertEqual(started[0][1][0], "宝宝别着急")
        self.assertTrue(started[0][2])
        self.assertEqual(audio.queue, [])


if __name__ == "__main__":
    unittest.main()
