"""Canonical wire protocol — single source of truth for all three sides.

Keep this aligned with docs/protocol.md. When adding a field or constant,
update docs/protocol.md in the same commit.

Car  (raspbot_remote/)  — re-exports via protocol.py shim
PC   (raspbot1/)        — imports + extends with PC-only WebRTC types
App  (RaspbotApp/)      — references the same token vocabulary and field names
"""

from dataclasses import dataclass
import hmac
import os
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlsplit


# ── Wire constants ────────────────────────────────────────────────

MSG_VIDEO   = 0x01
MSG_COMMAND = 0x02
MSG_ENV     = 0x03

AUTH_QUERY_KEY = "token"
AUTH_FIELD     = "auth_token"

# Playlist navigation sentinels
PLAY_SONG_NEXT   = "__next__"
PLAY_SONG_PREV   = "__prev__"
PLAY_SONG_RANDOM = "__random__"


# ── Alarm token vocabulary ────────────────────────────────────────
#  Car (care_policy.py) emits these in EnvPacket.alarm, joined with '+'.
#  PC bridges them as-is.  App (AlarmPolicy.kt) parses and translates them.

ALARM_TOKEN_CLOSE_DISTANCE  = "close_distance"
ALARM_TOKEN_SMOKE           = "smoke"
ALARM_TOKEN_CRY             = "cry"
ALARM_TOKEN_CLIFF           = "cliff"
ALARM_TOKEN_LOW_BATTERY     = "low_battery"
ALARM_TOKEN_TEMP_HIGH       = "temp_high"
ALARM_TOKEN_TEMP_LOW        = "temp_low"
ALARM_TOKEN_LIGHT_LOW       = "light_low"
ALARM_TOKEN_LIGHT_HIGH      = "light_high"
ALARM_TOKEN_LIGHT_CHANGED   = "light_changed"

ALARM_TOKENS: set[str] = {
    ALARM_TOKEN_CLOSE_DISTANCE,
    ALARM_TOKEN_SMOKE,
    ALARM_TOKEN_CRY,
    ALARM_TOKEN_CLIFF,
    ALARM_TOKEN_LOW_BATTERY,
    ALARM_TOKEN_TEMP_HIGH,
    ALARM_TOKEN_TEMP_LOW,
    ALARM_TOKEN_LIGHT_LOW,
    ALARM_TOKEN_LIGHT_HIGH,
    ALARM_TOKEN_LIGHT_CHANGED,
}


# ── Utility helpers ────────────────────────────────────────────────

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


# ── Auth helpers ───────────────────────────────────────────────────

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
        f"{component} refuses to bind {host!r} without RASPBOT_AUTH_TOKEN; "
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


# ── Cliff detection (car-only logic, defined here for single-source) ─

def cliff_level(track) -> int:
    """Progressive cliff level from 4-channel track sensors.

    0 = safe (0-1 dark)
    1 = warning (≥2 dark, or both front sensors dark)
    2 = danger  (≥3 dark)
    3 = cliff   (all 4 dark)
    """
    if not isinstance(track, list) or len(track) < 4:
        return 0
    try:
        values = [int(v) for v in track[:4]]
    except (TypeError, ValueError):
        return 0
    dark = sum(1 for v in values if v == 0)
    front_both_dark = values[0] == 0 and values[1] == 0
    if dark >= 4:
        return 3
    if dark >= 3:
        return 2
    if dark >= 2 or front_both_dark:
        return 1
    return 0


def cliff_direction(pitch, roll, imu_healthy,
                    pitch_down_deg=-8.0, pitch_up_deg=8.0, roll_tilt_deg=10.0) -> str:
    """Classify cliff danger direction from IMU attitude angles (degrees).

    Returns "forward" | "rear" | "side" | "suspended".
    """
    if not imu_healthy:
        return "suspended"
    if abs(roll) > abs(pitch) and abs(roll) > roll_tilt_deg:
        return "side"
    if pitch < pitch_down_deg:
        return "forward"
    if pitch > pitch_up_deg:
        return "rear"
    return "suspended"


def is_cliff_track(track) -> bool:
    """Return True if all four track sensors report cliff."""
    return cliff_level(track) >= 3


# ── Wire data classes ──────────────────────────────────────────────

@dataclass
class CommandPacket:
    action: str = "stop"
    servo_angle: float = 90.0
    servo_angle2: float = 90.0
    speed: int = 80
    left_speed: int = 80
    right_speed: int = 80
    source: str = ""
    tracking_mode: bool = False
    audio_volume: Optional[int] = None
    detecting: bool = False
    play_song: str = ""
    stop_audio: bool = False
    remote_crying: Optional[bool] = None
    remote_cry_score: Optional[int] = None
    remote_alarm: Optional[str] = None
    reply_text: str = ""
    tts_text: str = ""
    intent_type: str = ""

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]):
        if not isinstance(payload, dict):
            return cls()
        speed = clamp_int(payload.get("speed", 80), 0, 255, 80)
        audio_volume = payload.get("audio_volume", None)
        # PC is the producer of remote_crying/remote_cry_score/remote_alarm;
        # prefer those keys, fall back to older crying/cry_score/alarm names
        crying_payload = payload.get("remote_crying", payload.get("crying", None))
        cry_score_payload = payload.get("remote_cry_score", payload.get("cry_score", None))
        alarm_payload = payload.get("remote_alarm", payload.get("alarm", None))
        remote_alarm = None if alarm_payload is None else str(alarm_payload).strip()
        return cls(
            action=str(payload.get("action", "stop") or "stop"),
            servo_angle=float(clamp_int(payload.get("servo_angle", 90), 0, 180, 90)),
            servo_angle2=float(clamp_int(payload.get("servo_angle2", 90), 0, 180, 90)),
            speed=speed,
            left_speed=clamp_int(payload.get("left_speed", speed), 0, 255, speed),
            right_speed=clamp_int(payload.get("right_speed", speed), 0, 255, speed),
            source=str(payload.get("source", "") or "").strip(),
            tracking_mode=as_bool(payload.get("tracking_mode", False)),
            audio_volume=None if audio_volume is None else clamp_int(audio_volume, 0, 100, 100),
            detecting=as_bool(payload.get("detecting", False)),
            play_song=str(payload.get("play_song", "") or "").strip(),
            stop_audio=as_bool(payload.get("stop_audio", False)),
            remote_crying=None if crying_payload is None else as_bool(crying_payload),
            remote_cry_score=None if cry_score_payload is None else clamp_int(cry_score_payload, 0, 100, 0),
            remote_alarm=remote_alarm,
            reply_text=str(payload.get("reply_text", "") or "").strip(),
            tts_text=str(payload.get("tts_text", "") or "").strip(),
            intent_type=str(payload.get("intent_type", "") or "").strip(),
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
    pcf8591_ok: bool = True
    battery_status: str = "OK"
    cliff_level: int = 0
    cliff_direction: str = ""

    def __post_init__(self):
        if not isinstance(self.track, list) or len(self.track) < 4:
            object.__setattr__(self, 'track', [1, 1, 1, 1])
        else:
            normalized = []
            for v in self.track[:4]:
                try:
                    normalized.append(int(v))
                except (TypeError, ValueError):
                    normalized.append(1)
            object.__setattr__(self, 'track', normalized)
        if not isinstance(self.alarm, str):
            object.__setattr__(self, 'alarm', str(self.alarm or ''))
        object.__setattr__(self, 'pcf8591_ok', as_bool(self.pcf8591_ok))
        if not isinstance(self.battery_status, str):
            object.__setattr__(self, 'battery_status', str(self.battery_status or 'OK'))
        try:
            object.__setattr__(self, 'cliff_level', int(self.cliff_level))
        except (TypeError, ValueError):
            object.__setattr__(self, 'cliff_level', 0)
        if not isinstance(self.cliff_direction, str):
            object.__setattr__(self, 'cliff_direction', str(self.cliff_direction or ''))

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
            "pcf8591_ok": self.pcf8591_ok,
            "battery_status": self.battery_status,
            "cliff_level": self.cliff_level,
            "cliff_direction": self.cliff_direction,
        }
