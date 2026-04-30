"""Command and environment packet models."""
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional


def _clamp_int(value: Any, min_v: int, max_v: int, default: int) -> int:
    try:
        return int(max(min_v, min(max_v, int(value))))
    except Exception:
        return int(default)


def _clamp_float(value: Any, min_v: float, max_v: float, default: float) -> float:
    try:
        return float(max(min_v, min(max_v, float(value))))
    except Exception:
        return float(default)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return False


@dataclass
class CommandPacket:
    action: str = 'stop'
    servo_angle: float = 90.0
    servo_angle2: float = 90.0
    speed: int = 0
    left_speed: int = 0
    right_speed: int = 0
    source: str = ''
    tracking_mode: bool = False
    audio_volume: Optional[int] = None
    detecting: bool = False
    play_song: str = ''
    stop_audio: bool = False
    remote_crying: Optional[bool] = None
    remote_cry_score: Optional[int] = None
    remote_alarm: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]):
        if not isinstance(payload, dict):
            return cls()
        speed = _clamp_int(payload.get('speed', 0), 0, 255, 0)
        audio_volume = payload.get('audio_volume')
        crying_payload = payload.get('remote_crying', payload.get('crying', None))
        cry_score_payload = payload.get('remote_cry_score', payload.get('cry_score', None))
        alarm_payload = payload.get('remote_alarm', payload.get('alarm', None))
        return cls(
            action=str(payload.get('action', 'stop') or 'stop'),
            servo_angle=_clamp_float(payload.get('servo_angle', 90.0), 0.0, 180.0, 90.0),
            servo_angle2=_clamp_float(payload.get('servo_angle2', 90.0), 0.0, 180.0, 90.0),
            speed=speed,
            left_speed=_clamp_int(payload.get('left_speed', speed), 0, 255, speed),
            right_speed=_clamp_int(payload.get('right_speed', speed), 0, 255, speed),
            source=str(payload.get('source', '') or '').strip(),
            tracking_mode=_as_bool(payload.get('tracking_mode', False)),
            audio_volume=None if audio_volume is None else _clamp_int(audio_volume, 0, 100, 100),
            detecting=_as_bool(payload.get('detecting', False)),
            play_song=str(payload.get('play_song', '') or '').strip(),
            stop_audio=_as_bool(payload.get('stop_audio', False)),
            remote_crying=None if crying_payload is None else _as_bool(crying_payload),
            remote_cry_score=None if cry_score_payload is None else _clamp_int(cry_score_payload, 0, 100, 0),
            remote_alarm=None if alarm_payload is None else str(alarm_payload).strip(),
        )

    def to_wire_dict(self) -> Dict[str, Any]:
        # Keep network protocol aligned with car-side CommandPacket.from_dict().
        # Debug/analysis fields stay local and are not sent over websocket.
        payload = {
            'action': self.action,
            'servo_angle': self.servo_angle,
            'servo_angle2': self.servo_angle2,
            'speed': self.speed,
            'left_speed': self.left_speed,
            'right_speed': self.right_speed,
            'detecting': self.detecting,
            'play_song': self.play_song,
            'stop_audio': self.stop_audio,
        }
        if self.source:
            payload['source'] = self.source
        if self.tracking_mode:
            payload['tracking_mode'] = self.tracking_mode
        if self.audio_volume is not None:
            payload['audio_volume'] = self.audio_volume
        if self.remote_crying is not None:
            payload['remote_crying'] = self.remote_crying
        if self.remote_cry_score is not None:
            payload['remote_cry_score'] = self.remote_cry_score
        if self.remote_alarm is not None:
            payload['remote_alarm'] = self.remote_alarm
        return payload

    def clone(self):
        return replace(self)


@dataclass
class EnvPacket:
    dist_cm: float = 999.0
    track: List[int] = field(default_factory=list)
    alarm: str = ''
    imu: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]):
        if not isinstance(payload, dict):
            return cls()
        imu_payload = payload.get('imu')
        if not isinstance(imu_payload, dict):
            imu_payload = {}
        track_payload = payload.get('track')
        track = track_payload if isinstance(track_payload, list) else []
        return cls(
            dist_cm=float(payload.get('dist_cm', 999.0) or 999.0),
            track=track,
            alarm=str(payload.get('alarm', '') or ''),
            imu=imu_payload,
            raw=dict(payload),
        )
