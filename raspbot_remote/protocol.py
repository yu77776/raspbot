"""Shared car-side wire protocol models.

Keep these fields aligned with docs/protocol.md and pc_modules/packets.py.
"""

from dataclasses import dataclass
import hmac
import os
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlsplit


MSG_VIDEO = 0x01
MSG_COMMAND = 0x02
MSG_ENV = 0x03

AUTH_QUERY_KEY = "token"
AUTH_FIELD = "auth_token"

# Shared playlist navigation sentinels — keep in sync with pc_modules/protocol.py.
PLAY_SONG_NEXT = "__next__"
PLAY_SONG_PREV = "__prev__"
PLAY_SONG_RANDOM = "__random__"


def resolve_auth_token(value: Optional[str] = None) -> str:
    return str(value if value is not None else os.getenv("RASPBOT_AUTH_TOKEN", "")).strip()


def _is_loopback_host(host: Any) -> bool:
    value = str(host or "").strip().lower()
    return value in {"localhost", "127.0.0.1", "::1"}


def validate_auth_config(
    host: Any,
    auth_token: Optional[str],
    *,
    component: str = "server",
    allow_insecure: Optional[bool] = None,
) -> None:
    token = resolve_auth_token(auth_token)
    if token:
        return
    if allow_insecure is None:
        allow_insecure = as_bool(os.getenv("RASPBOT_ALLOW_INSECURE", "0"))
    if allow_insecure or _is_loopback_host(host):
        return
    raise RuntimeError(
        f"{component} refuses to bind {host!r} without RASPBOT_AUTH_TOKEN "
        "set RASPBOT_ALLOW_INSECURE=1 only for isolated lab networks"
    )


def safe_ws_path(ws) -> str:
    path = getattr(ws, "path", None)
    if path:
        return str(path)
    req = getattr(ws, "request", None)
    if req is not None:
        return str(getattr(req, "path", "") or "")
    return ""


def auth_token_from_ws(ws) -> str:
    path = safe_ws_path(ws)
    query = urlsplit(path).query
    params = dict(parse_qsl(query, keep_blank_values=True))
    return str(params.get(AUTH_QUERY_KEY, "") or "").strip()


def is_ws_authorized(ws, expected_token: Optional[str]) -> bool:
    token = resolve_auth_token(expected_token)
    if not token:
        return True
    return hmac.compare_digest(auth_token_from_ws(ws), token)


def is_cliff_track(track) -> bool:
    """Return True if all four track sensors report cliff (value == 0)."""
    if not isinstance(track, list) or len(track) < 4:
        return False
    try:
        return all(int(v) == 0 for v in track[:4])
    except (TypeError, ValueError):
        return False


def clamp_int(value: Any, min_v: int, max_v: int, default: int) -> int:
    try:
        return int(max(min_v, min(max_v, int(value))))
    except Exception:
        return int(default)


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


@dataclass
class CommandPacket:
    action: str = "stop"
    servo_angle: int = 90
    servo_angle2: int = 90
    speed: int = 80
    left_speed: int = 80
    right_speed: int = 80
    audio_volume: Optional[int] = None
    detecting: bool = False
    play_song: str = ""
    stop_audio: bool = False
    remote_crying: Optional[bool] = None
    remote_cry_score: Optional[int] = None
    remote_alarm: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]):
        if not isinstance(payload, dict):
            return cls()
        speed = clamp_int(payload.get("speed", 80), 0, 255, 80)
        audio_volume = payload.get("audio_volume", None)
        crying_payload = payload.get("crying", payload.get("remote_crying", None))
        cry_score_payload = payload.get("cry_score", payload.get("remote_cry_score", None))
        alarm_payload = payload.get("alarm", payload.get("remote_alarm", None))
        remote_alarm = None if alarm_payload is None else str(alarm_payload).strip()
        return cls(
            action=str(payload.get("action", "stop") or "stop"),
            servo_angle=clamp_int(payload.get("servo_angle", 90), 0, 180, 90),
            servo_angle2=clamp_int(payload.get("servo_angle2", 90), 0, 180, 90),
            speed=speed,
            left_speed=clamp_int(payload.get("left_speed", speed), 0, 255, speed),
            right_speed=clamp_int(payload.get("right_speed", speed), 0, 255, speed),
            audio_volume=None if audio_volume is None else clamp_int(audio_volume, 0, 100, 100),
            detecting=as_bool(payload.get("detecting", False)),
            play_song=str(payload.get("play_song", "") or "").strip(),
            stop_audio=as_bool(payload.get("stop_audio", False)),
            remote_crying=None if crying_payload is None else as_bool(crying_payload),
            remote_cry_score=None if cry_score_payload is None else clamp_int(cry_score_payload, 0, 100, 0),
            remote_alarm=remote_alarm,
        )


@dataclass
class ImuPacket:
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    yaw_rate: float = 0.0
    healthy: bool = False
    calibrated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "roll": self.roll,
            "pitch": self.pitch,
            "yaw": self.yaw,
            "yaw_rate": self.yaw_rate,
            "healthy": self.healthy,
            "calibrated": self.calibrated,
        }


@dataclass
class EnvPacket:
    light: int
    light_lux: int
    temp_raw: int
    temp_c: float
    smoke: int
    volume: int
    crying: bool
    cry_score: int
    dist_cm: float
    track: List[int]
    alarm: str
    imu: Optional[ImuPacket]
    fps: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "light": self.light,
            "light_lux": self.light_lux,
            "temp_raw": self.temp_raw,
            "temp_c": self.temp_c,
            "smoke": self.smoke,
            "volume": self.volume,
            "crying": self.crying,
            "cry_score": self.cry_score,
            "dist_cm": self.dist_cm,
            "track": self.track,
            "alarm": self.alarm,
            "imu": self.imu.to_dict() if self.imu else None,
            "fps": self.fps,
        }
