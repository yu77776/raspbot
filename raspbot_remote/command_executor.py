"""Command execution boundary for car-side modules."""

import os
import time
from typing import Callable

from protocol import CommandPacket, EnvPacket


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
    ):
        self.motor = motor
        self.audio = audio
        self.oled = oled
        self.env_provider = env_provider
        self.mark_command_seen = mark_command_seen
        self.set_remote_cry_state = set_remote_cry_state
        self.note_app_audio_volume = note_app_audio_volume
        self.sync_oled_alarm = sync_oled_alarm

    def execute(self, cmd: CommandPacket):
        if not isinstance(cmd, CommandPacket):
            cmd = CommandPacket.from_dict(cmd)

        self.set_remote_cry_state(cmd)
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

        display_song_cmd = song_cmd
        if song_cmd and not is_sensor_event:
            resolved_song = self.audio.resolve_song(song_cmd)
            if resolved_song:
                display_song_cmd = resolved_song
                self.audio.enqueue("song", resolved_song)
            else:
                print("[AUDIO] no default song found")
        if cmd.stop_audio:
            self.audio.clear()

        dist = env_packet.dist_cm
        if action == "forward" and dist < 30:
            print(f"[SAFE] block forward at dist={dist:.1f}cm (<30cm)")
            action = "stop"
        self.mark_command_seen(action, speed, cmd.left_speed, cmd.right_speed)

        self.motor.set_servo(1, servo1)
        self.motor.set_servo(2, servo2)
        self.oled.set_pan(servo1)

        self.motor.execute_motion(
            action,
            speed,
            left_speed=cmd.left_speed,
            right_speed=cmd.right_speed,
            env_packet=env_packet,
        )

        if action in ("spin_left", "spin_right"):
            self.oled.set_state("turning")
        elif cmd.detecting:
            self.oled.set_state("tracking")
        else:
            self.oled.set_state("idle")

        if song_cmd and not is_sensor_event:
            song_name = os.path.splitext(os.path.basename(display_song_cmd))[0]
            self.oled.push_event("music", song_name, duration=3.0)
        elif is_sensor_event:
            parts = song_cmd.split("__")
            if len(parts) >= 4:
                self.oled.push_event(
                    "sensor",
                    {"label": parts[2], "text": parts[3]},
                    duration=3.0,
                )

        self.sync_oled_alarm(env_packet)
