import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT.parent / "raspbot_remote"
if str(REMOTE) not in sys.path:
    sys.path.insert(0, str(REMOTE))

from car_server_modular import CarServer, _is_app_auto_status_payload
from command_executor import CommandExecutor
from modules.oled_face import FaceEngine
from protocol import CommandPacket, EnvPacket, PLAY_SONG_NEXT, PLAY_SONG_PREV


def make_env(**overrides):
    data = {
        "light": 0,
        "light_lux": 120,
        "temp_raw": 0,
        "temp_c": 26.0,
        "smoke": 0,
        "volume": 50,
        "crying": False,
        "cry_score": 0,
        "dist_cm": 80.0,
        "track": [1, 1, 1, 1],
        "alarm": "",
        "imu": None,
        "fps": 0,
    }
    data.update(overrides)
    return EnvPacket(**data)


class FakeMotor:
    def __init__(self):
        self.motion = None

    def set_servo(self, *_args):
        pass

    def execute_motion(self, action, speed, **kwargs):
        self.motion = (action, speed, kwargs)


class FakeAudio:
    def __init__(self):
        self.volume = 55
        self.set_volumes = []
        self.enqueued_songs = []
        self.queue = []

    def set_volume(self, volume):
        self.volume = int(volume)
        self.set_volumes.append(int(volume))

    def enqueue_song(self, song_cmd):
        self.enqueued_songs.append(song_cmd)
        if song_cmd == PLAY_SONG_NEXT:
            return "next-song.mp3"
        if song_cmd == PLAY_SONG_PREV:
            return "prev-song.mp3"
        return "default-song.mp3"

    def clear(self):
        pass

    def enqueue(self, *_args):
        self.queue.append(_args)


class FakeOled:
    def __init__(self):
        self.events = []
        self.states = []
        self.modes = []

    def set_pan(self, *_args):
        pass

    def set_state(self, state):
        self.states.append(state)

    def set_mode(self, mode):
        self.modes.append(mode)

    def push_event(self, kind, value=None, duration=2.5):
        self.events.append((kind, value, duration))

    def clear_event(self, kind=None):
        self.events.append(("clear_event", kind, None))


class FakeDraw:
    def __init__(self):
        self.text_calls = []

    def text(self, xy, text, font=None, fill=1):
        self.text_calls.append((xy, text, font, fill))

    def rectangle(self, *_args, **_kwargs):
        pass

    def textlength(self, text, font=None):
        return len(str(text)) * 6


class TestOledStatus(unittest.TestCase):
    def test_alarm_text_is_short_for_small_oled(self):
        cases = [
            (make_env(alarm="temp_high", temp_c=31.6), "TEMP HI 31.6"),
            (make_env(alarm="temp_low", temp_c=17.2), "TEMP LO 17.2"),
            (make_env(alarm="close_distance", dist_cm=18.4), "CLOSE 18"),
            (make_env(alarm="light_changed", light_lux=620), "LIGHT +/-"),
            (make_env(alarm="cry", cry_score=76), "CRY 76"),
            (make_env(alarm="smoke", smoke=333), "SMOKE 333"),
        ]

        for env_packet, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(CarServer._oled_alarm_text(None, env_packet), expected)

    def test_volume_command_pushes_oled_volume_event(self):
        oled = FakeOled()
        executor = make_executor(oled=oled)

        executor.execute(CommandPacket(audio_volume=72))

        self.assertIn(("volume", 72, 1.5), oled.events)

    def test_cry_sync_command_does_not_execute_motion(self):
        calls = []
        executor = make_executor(
            oled=FakeOled(),
            mark_command_seen=lambda *args: calls.append(("seen", args)),
        )

        executor.execute(CommandPacket(source="cry_sync", remote_crying=True, remote_cry_score=91))

        self.assertEqual(calls, [])
        self.assertFalse(_is_app_auto_status_payload({
            "source": "cry_sync",
            "remote_crying": True,
            "remote_cry_score": 91,
        }))

    def test_app_auto_status_payload_is_ignored_by_car_control_owner(self):
        self.assertTrue(_is_app_auto_status_payload({
            "source": "app_auto",
            "tracking_mode": True,
            "action": "stop",
        }))
        self.assertFalse(_is_app_auto_status_payload({
            "source": "app",
            "tracking_mode": False,
            "action": "backward",
        }))

    def test_env_cry_alarm_enqueues_care_tts(self):
        server = object.__new__(CarServer)
        server.audio = FakeAudio()
        server._baby_tts_for_alarm = lambda alarm: "宝宝别着急，我陪着你呢" if "cry" in alarm else ""

        server._enqueue_baby_tts_for_env(make_env(alarm="cry", crying=True, cry_score=91))

        self.assertIn(("tts", "宝宝别着急，我陪着你呢"), server.audio.queue)

    def test_music_navigation_pushes_action_label(self):
        oled = FakeOled()
        executor = make_executor(oled=oled)

        executor.execute(CommandPacket(play_song=PLAY_SONG_NEXT))
        executor.execute(CommandPacket(play_song=PLAY_SONG_PREV))

        self.assertIn(("music", {"action": "NEXT", "name": "next-song"}, 30.0), oled.events)
        self.assertIn(("music", {"action": "PREV", "name": "prev-song"}, 30.0), oled.events)

    def test_stop_audio_clears_music_event(self):
        oled = FakeOled()
        executor = make_executor(oled=oled)

        executor.execute(CommandPacket(stop_audio=True))

        self.assertIn(("clear_event", "music", None), oled.events)

    def test_manual_forward_block_threshold_is_less_sensitive(self):
        motor = FakeMotor()
        executor = make_executor(oled=FakeOled(), motor=motor, env_provider=lambda: make_env(dist_cm=6.0, alarm="close_distance"))

        executor.execute(CommandPacket(action="forward", speed=80, source="app"))

        self.assertEqual(motor.motion[0], "forward")

        executor = make_executor(oled=FakeOled(), motor=motor, env_provider=lambda: make_env(dist_cm=4.0, alarm=""))
        executor.execute(CommandPacket(action="forward", speed=80, source="app"))

        self.assertEqual(motor.motion[0], "stop")

        executor = make_executor(oled=FakeOled(), motor=motor, env_provider=lambda: make_env(dist_cm=4.0, alarm=""))
        executor.execute(CommandPacket(action="backward", speed=80, source="app"))

        self.assertEqual(motor.motion[0], "backward")

    def test_auto_mode_still_honors_close_distance_alarm(self):
        motor = FakeMotor()
        executor = make_executor(oled=FakeOled(), motor=motor, env_provider=lambda: make_env(dist_cm=18.0, alarm="close_distance"))

        executor.execute(CommandPacket(action="forward", speed=80, tracking_mode=True))

        self.assertEqual(motor.motion[0], "backward")

    def test_auto_tracking_without_detection_uses_searching_face(self):
        oled = FakeOled()
        executor = make_executor(oled=oled)

        executor.execute(CommandPacket(action="stop", tracking_mode=True, detecting=False))

        # Tracking mode without detection stays "searching" — the OLED engine
        # handles the 20s searching→sleeping auto-transition internally.
        self.assertIn("searching", oled.states)
        self.assertNotIn("sleeping", oled.states)

    def test_manual_too_close_clears_pending_close_backoff(self):
        motor = FakeMotor()
        envs = iter([
            make_env(dist_cm=18.0, alarm="close_distance"),
            make_env(dist_cm=4.0, alarm="close_distance"),
        ])
        executor = make_executor(oled=FakeOled(), motor=motor, env_provider=lambda: next(envs))

        executor.execute(CommandPacket(action="forward", speed=80, tracking_mode=True))
        self.assertEqual(motor.motion[0], "backward")

        executor.execute(CommandPacket(action="left", speed=80, source="app"))
        self.assertEqual(motor.motion[0], "stop")
        self.assertEqual(motor.motion[1], 0)

    def test_face_engine_tracks_mode_badge_label(self):
        face = FaceEngine()

        face.set_mode("manual")
        self.assertEqual(face.mode_label, "MANUAL")

        face.set_mode("auto")
        self.assertEqual(face.mode_label, "AUTO")

    def test_alarm_text_is_sanitized_for_ascii_oled_warning_line(self):
        face = FaceEngine()

        self.assertEqual(face._sanitize_alarm_text("温度高 31.6°C"), "31.6C")
        self.assertEqual(face._sanitize_alarm_text("LIGHT ± 200"), "LIGHT +/- 200")

    def test_music_title_repairs_utf8_mojibake(self):
        face = FaceEngine()

        mojibake = "稻香-周杰伦".encode("utf-8").decode("latin1")

        self.assertEqual(face._repair_mojibake(mojibake), "稻香-周杰伦")
        self.assertEqual(face._repair_mojibake("稻香-周杰伦"), "稻香-周杰伦")

    def test_volume_event_can_temporarily_overlay_alarm(self):
        face = FaceEngine()

        face.set_alarm("CLOSE 18")
        face.push_event("volume", 72, duration=1.5)

        self.assertTrue(face._event_overlays_alarm(face._pop_event()))

    def test_compact_oled_text_does_not_use_negative_y(self):
        face = FaceEngine()
        draw = FakeDraw()

        face._draw_mode_badge(draw)
        face._draw_text_center(draw, 0, "VOL", face.font_en)
        face._draw_text_center_inv(draw, 0, "! ALERT", face.font_en)

        self.assertTrue(draw.text_calls)
        self.assertTrue(all(y >= 0 for (x, y), *_ in draw.text_calls))


def make_executor(oled, motor=None, env_provider=None, mark_command_seen=None):
    return CommandExecutor(
        motor=motor or FakeMotor(),
        audio=FakeAudio(),
        oled=oled,
        env_provider=env_provider or (lambda: make_env()),
        mark_command_seen=mark_command_seen or (lambda *_args: None),
        set_remote_cry_state=lambda *_args: None,
        note_app_audio_volume=lambda *_args: None,
        sync_oled_alarm=lambda *_args: None,
    )


if __name__ == "__main__":
    unittest.main()
