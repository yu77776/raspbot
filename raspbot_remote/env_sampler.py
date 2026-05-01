"""Environment packet sampling for the car server."""

import time
from typing import Callable, Optional, Tuple

from protocol import EnvPacket, ImuPacket


class EnvSampler:
    def __init__(
        self,
        pcf8591,
        ultrasonic,
        infrared,
        imu,
        camera,
        audio,
        *,
        cry_alarm_score_min: int,
        remote_cry_provider: Callable[[], Tuple[Optional[bool], Optional[int], Optional[str]]],
        knob_volume_enabled: bool = True,
        knob_volume_deadband: int = 3,
        knob_volume_after_app_grace_sec: float = 1.5,
    ):
        self.pcf8591 = pcf8591
        self.ultrasonic = ultrasonic
        self.infrared = infrared
        self.imu = imu
        self.camera = camera
        self.audio = audio
        self.cry_alarm_score_min = int(max(0, min(100, int(cry_alarm_score_min))))
        self.remote_cry_provider = remote_cry_provider
        self.knob_volume_enabled = bool(knob_volume_enabled)
        self.knob_volume_deadband = int(max(0, min(20, int(knob_volume_deadband))))
        self.knob_volume_after_app_grace_sec = float(knob_volume_after_app_grace_sec)
        self._last_applied_knob_volume: Optional[int] = None
        self._last_app_audio_volume_ts = 0.0

    def note_app_audio_volume(self, volume: int) -> None:
        self._last_app_audio_volume_ts = time.monotonic()
        self._last_applied_knob_volume = int(max(0, min(100, int(volume))))

    def sample(self) -> EnvPacket:
        env = self.pcf8591.get_data()
        dist = self.ultrasonic.get_distance()
        track = self.infrared.get_data().get("track", [1, 1, 1, 1])
        volume = int(env.get("volume", 0))
        self._apply_knob_volume(volume)

        crying, cry_score = False, 0
        remote_crying, remote_cry_score, remote_alarm = self.remote_cry_provider()
        if remote_crying is not None:
            crying = remote_crying
        if remote_cry_score is not None:
            cry_score = remote_cry_score

        alarms = []
        if env.get("smoke_alarm"):
            alarms.append("smoke")
        if _is_cliff_track(track):
            alarms.append("cliff")
        if crying and cry_score >= self.cry_alarm_score_min:
            alarms.append("cry")
        if remote_alarm:
            alarms.append(remote_alarm)

        return EnvPacket(
            light=int(env.get("light", 0)),
            light_lux=int(env.get("light_lux", 0)),
            temp_raw=int(env.get("temp_raw", 0)),
            temp_c=float(env.get("temp_c", 0.0)),
            smoke=int(env.get("smoke", 0)),
            volume=volume,
            crying=crying,
            cry_score=cry_score,
            dist_cm=round(float(dist), 1),
            track=track,
            alarm="+".join(alarms),
            imu=self._sample_imu(),
            fps=int(self.camera.get_fps()),
        )

    def _sample_imu(self) -> Optional[ImuPacket]:
        imu_data = self.imu.get_data() if self.imu.enabled else {}
        if not imu_data:
            return None
        gyro = imu_data.get("gyro_dps", [0.0, 0.0, 0.0])
        return ImuPacket(
            roll=float(imu_data.get("roll", 0.0)),
            pitch=float(imu_data.get("pitch", 0.0)),
            yaw=float(imu_data.get("yaw", 0.0)),
            yaw_rate=float(gyro[2]) if len(gyro) > 2 else 0.0,
            healthy=bool(imu_data.get("healthy", False)),
            calibrated=bool(imu_data.get("calibrated", False)),
        )

    def _apply_knob_volume(self, volume: int) -> None:
        if not self.knob_volume_enabled:
            return
        now = time.monotonic()
        if now - self._last_app_audio_volume_ts < self.knob_volume_after_app_grace_sec:
            return
        volume = int(max(0, min(100, int(volume))))
        if self._last_applied_knob_volume is not None:
            if abs(volume - self._last_applied_knob_volume) < self.knob_volume_deadband:
                return
        self._last_applied_knob_volume = volume
        self.audio.set_volume(volume)


def _is_cliff_track(track) -> bool:
    if not isinstance(track, list) or len(track) < 4:
        return False
    try:
        return all(int(v) == 0 for v in track[:4])
    except (TypeError, ValueError):
        return False
