"""Command execution boundary for car-side modules."""

import os
import time
from typing import Callable

from logger_setup import setup_logger
from protocol import CommandPacket, EnvPacket, PLAY_SONG_NEXT, PLAY_SONG_PREV, is_cliff_track

logger = setup_logger('raspbot.executor')


class CommandExecutor:
    def __init__(
        self,
        *,
        motor,
        audio,
        oled,
        env_provider: Callable[[], EnvPacket],
        mark_command_seen: Callable[[str, int, int, int], None],
        set_remote_cry_state: Callable[[CommandPacket], None],
        note_app_audio_volume: Callable[[int], None],
        sync_oled_alarm: Callable[[EnvPacket], None],
        baby_tts_provider: Callable[[str], str] = None,
        buzzer=None,
    ):
        self.motor = motor
        self.audio = audio
        self.oled = oled
        self.env_provider = env_provider
        self.mark_command_seen = mark_command_seen
        self.set_remote_cry_state = set_remote_cry_state
        self.note_app_audio_volume = note_app_audio_volume
        self.sync_oled_alarm = sync_oled_alarm
        self.baby_tts_provider = baby_tts_provider
        self.buzzer = buzzer
        self.cliff_buzzer_enabled = True
        self.cliff_back_speed = int(max(0, min(255, int(os.getenv("RASPBOT_CLIFF_BACK_SPEED", "70")))))
        self.cliff_back_sec = float(os.getenv("RASPBOT_CLIFF_BACK_SEC", "0.35"))
        self.cliff_forward_speed = int(max(0, min(255, int(os.getenv("RASPBOT_CLIFF_FORWARD_SPEED", "70")))))
        self.cliff_forward_sec = float(os.getenv("RASPBOT_CLIFF_FORWARD_SEC", "0.35"))
        self.close_back_speed = int(max(0, min(255, int(os.getenv("RASPBOT_CLOSE_BACK_SPEED", "70")))))
        self.close_back_sec = float(os.getenv("RASPBOT_CLOSE_BACK_SEC", "0.05"))
        self.manual_forward_block_cm = float(os.getenv("RASPBOT_MANUAL_FORWARD_BLOCK_CM", "5"))
        self._cliff_back_until = 0.0
        self._cliff_forward_until = 0.0
        self._close_back_until = 0.0

    def execute(self, cmd: CommandPacket):
        if not isinstance(cmd, CommandPacket):
            cmd = CommandPacket.from_dict(cmd)

        self.set_remote_cry_state(cmd)
        if str(cmd.source or "").strip().lower() == "cry_sync":
            return

        servo1 = cmd.servo_angle
        servo2 = cmd.servo_angle2
        speed = cmd.speed
        env_packet = self.env_provider()
        action = cmd.action
        song_cmd = str(cmd.play_song or "").strip()
        is_sensor_event = song_cmd.startswith("__sensor__")

        if cmd.audio_volume is not None:
            self.note_app_audio_volume(cmd.audio_volume)
            self.audio.set_volume(cmd.audio_volume)
            self.oled.push_event("volume", cmd.audio_volume, duration=1.5)

        display_song_cmd = song_cmd
        if song_cmd and not is_sensor_event:
            self.note_app_audio_volume(self.audio.volume)
            resolved_song = self.audio.enqueue_song(song_cmd)
            if resolved_song:
                display_song_cmd = resolved_song
                logger.info('enqueue song=%s cmd=%s', resolved_song, song_cmd)
            else:
                logger.warning('no default song found')
        if cmd.stop_audio:
            self.audio.clear()
            clear_event = getattr(self.oled, "clear_event", None)
            if callable(clear_event):
                clear_event("music")

        tts = str(cmd.tts_text or cmd.reply_text or "").strip()
        if tts:
            self.audio.enqueue('tts', tts)
            logger.info('enqueue tts=%s', tts)

        dist = env_packet.dist_cm
        now = time.monotonic()
        care_tts = self._baby_tts_for_alarm(env_packet.alarm)
        if care_tts and not tts:
            self.audio.enqueue('tts', care_tts)
            logger.info('enqueue care tts=%s', care_tts)

        cliff_level = int(getattr(env_packet, 'cliff_level', 0) or 0)
        cliff_dir = str(getattr(env_packet, 'cliff_direction', '') or '')

        # Fallback: old-format packet without debounced cliff fields
        if cliff_level == 0 and _is_cliff_alarm(env_packet):
            cliff_level = 3
            cliff_dir = "suspended"

        manual_app = str(cmd.source or "").strip().lower() == "app" and not cmd.tracking_mode and not cmd.detecting
        manual_too_close = manual_app and _distance_at_or_below(env_packet, self.manual_forward_block_cm)
        if manual_app:
            self._close_back_until = 0.0
        close_distance = False if manual_app else _is_close_distance_alarm(
            env_packet,
            threshold_cm=self.manual_forward_block_cm if manual_app else 20.0,
            honor_alarm=not manual_app,
        )

        # ── cliff level 3: confirmed cliff → direction-based escape ──
        if cliff_level >= 3:
            if cliff_dir == "forward":
                # Nose down — danger ahead → backward escape
                if self._cliff_back_until <= now:
                    self._cliff_back_until = now + self.cliff_back_sec
                    if self.buzzer is not None and self.cliff_buzzer_enabled:
                        self.buzzer.beep_pattern(3, 0.1, 0.1)
                    logger.warning(
                        'cliff FORWARD track=%s pitch=%.1f -> backward %.2fs speed=%s',
                        getattr(env_packet, 'track', []),
                        _env_pitch(env_packet), self.cliff_back_sec, self.cliff_back_speed,
                    )
                else:
                    self._cliff_back_until = max(self._cliff_back_until, now + self.cliff_back_sec)
                self._cliff_forward_until = 0.0
            elif cliff_dir == "rear":
                # Nose up — rear at edge, front lifted → forward escape (NOT backward!)
                if self._cliff_forward_until <= now:
                    self._cliff_forward_until = now + self.cliff_forward_sec
                    if self.buzzer is not None and self.cliff_buzzer_enabled:
                        self.buzzer.beep_pattern(3, 0.1, 0.1)
                    logger.warning(
                        'cliff REAR track=%s pitch=%.1f -> forward %.2fs speed=%s',
                        getattr(env_packet, 'track', []),
                        _env_pitch(env_packet), self.cliff_forward_sec, self.cliff_forward_speed,
                    )
                else:
                    self._cliff_forward_until = max(self._cliff_forward_until, now + self.cliff_forward_sec)
                self._cliff_back_until = 0.0
            else:
                # "side" tilt or "suspended" → stop, don't move
                self._cliff_back_until = 0.0
                self._cliff_forward_until = 0.0
                self._close_back_until = 0.0
                if self.buzzer is not None and self.cliff_buzzer_enabled:
                    self.buzzer.beep_pattern(5, 0.05, 0.05)
                logger.warning(
                    'cliff dir=%s track=%s pitch=%.1f roll=%.1f -> stop',
                    cliff_dir, getattr(env_packet, 'track', []),
                    _env_pitch(env_packet), _env_roll(env_packet),
                )
                action = "stop"
                speed = 0
                cmd.left_speed = 0
                cmd.right_speed = 0
        elif cliff_level >= 2:
            # ── cliff level 2: danger → block motion toward danger ──
            self._cliff_back_until = 0.0
            self._cliff_forward_until = 0.0
            if cliff_dir == "forward":
                if action in ("forward",):
                    action = "stop"
                    speed = 0
                    logger.warning('cliff danger forward -> block forward motion')
            elif cliff_dir == "rear":
                if action in ("backward",):
                    action = "stop"
                    speed = 0
                    logger.warning('cliff danger rear -> block backward motion')
            elif cliff_dir in ("side", "suspended"):
                action = "stop"
                speed = 0
                self._close_back_until = 0.0
                logger.warning('cliff danger dir=%s -> stop', cliff_dir)
        elif cliff_level >= 1:
            # ── cliff level 1: warning → block forward, limit speed ──
            self._cliff_back_until = 0.0
            self._cliff_forward_until = 0.0
            if action == "forward":
                action = "stop"
                speed = 0
            speed = min(speed, 40)
            cmd.left_speed = min(cmd.left_speed, 40)
            cmd.right_speed = min(cmd.right_speed, 40)
        else:
            # ── safe ──
            pass

        if not close_distance or cliff_level >= 2:
            self._close_back_until = 0.0
        elif close_distance and self._close_back_until <= now:
            self._close_back_until = now + self.close_back_sec
            logger.warning('close distance dist=%.1fcm -> backward %.2fs', dist, self.close_back_sec)

        # Apply escape timers
        if now < self._cliff_back_until:
            action = "backward"
            speed = max(speed, self.cliff_back_speed)
            cmd.left_speed = self.cliff_back_speed
            cmd.right_speed = self.cliff_back_speed
        elif now < self._cliff_forward_until:
            action = "forward"
            speed = max(speed, self.cliff_forward_speed)
            cmd.left_speed = self.cliff_forward_speed
            cmd.right_speed = self.cliff_forward_speed
        elif close_distance or now < self._close_back_until:
            action = "backward"
            speed = self.close_back_speed
            cmd.left_speed = self.close_back_speed
            cmd.right_speed = self.close_back_speed
        if manual_too_close and action not in ("stop", "backward"):
            if action != "stop":
                logger.warning('block manual motion at dist=%.1fcm (<=%.1fcm)', dist, self.manual_forward_block_cm)
            action = "stop"
            speed = 0
            cmd.left_speed = 0
            cmd.right_speed = 0
        elif action == "forward" and dist < self.manual_forward_block_cm:
            logger.warning('block forward at dist=%.1fcm (<%.1fcm)', dist, self.manual_forward_block_cm)
            action = "stop"
        self.mark_command_seen(action, speed, cmd.left_speed, cmd.right_speed)

        self.motor.set_servo(1, servo1)
        self.motor.set_servo(2, servo2)
        self.oled.set_pan(servo1)
        self.oled.set_mode("auto" if cmd.tracking_mode or cmd.detecting else "manual")

        self.motor.execute_motion(
            action,
            speed,
            left_speed=cmd.left_speed,
            right_speed=cmd.right_speed,
            env_packet=env_packet,
        )

        if cmd.detecting:
            self.oled.set_state("tracking")
        elif cmd.tracking_mode:
            self.oled.set_state("sleeping" if action == "stop" else "searching")
        else:
            self.oled.set_state("idle")

        if song_cmd and not is_sensor_event:
            song_name = os.path.splitext(os.path.basename(display_song_cmd))[0]
            self.oled.push_event("music", _music_event_value(song_cmd, song_name), duration=30.0)
        elif is_sensor_event:
            parts = song_cmd.split("__")
            if len(parts) >= 4:
                self.oled.push_event(
                    "sensor",
                    {"label": parts[2], "text": parts[3]},
                    duration=3.0,
                )

        self.sync_oled_alarm(env_packet)

    def _baby_tts_for_alarm(self, alarm: str) -> str:
        if self.baby_tts_provider is None:
            return ""
        try:
            return str(self.baby_tts_provider(alarm) or "").strip()
        except Exception as exc:
            logger.warning("baby tts provider error: %s", exc)
            return ""


def _is_cliff_alarm(env_packet: EnvPacket) -> bool:
    alarm = str(getattr(env_packet, "alarm", "") or "").lower()
    if "cliff" in alarm or "track_empty" in alarm or "suspend" in alarm:
        return True
    return is_cliff_track(getattr(env_packet, "track", None))


def _env_pitch(env_packet: EnvPacket) -> float:
    imu = getattr(env_packet, "imu", None)
    if imu is None:
        return 0.0
    return float(getattr(imu, "pitch", 0.0) or 0.0)


def _env_roll(env_packet: EnvPacket) -> float:
    imu = getattr(env_packet, "imu", None)
    if imu is None:
        return 0.0
    return float(getattr(imu, "roll", 0.0) or 0.0)


def _is_close_distance_alarm(env_packet: EnvPacket, threshold_cm: float = 20.0, honor_alarm: bool = True) -> bool:
    alarm = str(getattr(env_packet, "alarm", "") or "").lower()
    if honor_alarm and "close_distance" in alarm:
        return True
    return _distance_at_or_below(env_packet, threshold_cm)


def _distance_at_or_below(env_packet: EnvPacket, threshold_cm: float) -> bool:
    try:
        return 0.0 <= float(getattr(env_packet, "dist_cm", 999.0)) <= float(threshold_cm)
    except Exception:
        return False


def _music_event_value(song_cmd: str, song_name: str):
    lower = str(song_cmd or "").strip().lower()
    if lower in {PLAY_SONG_NEXT, "next"}:
        return {"action": "NEXT", "name": song_name}
    if lower in {PLAY_SONG_PREV, "__previous__", "prev", "previous"}:
        return {"action": "PREV", "name": song_name}
    return {"action": "PLAY", "name": song_name}
