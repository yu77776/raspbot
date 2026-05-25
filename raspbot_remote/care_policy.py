"""Care-oriented alarm and response policy for baby companionship."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from protocol import cliff_direction, cliff_level, is_cliff_track


@dataclass(frozen=True)
class CarePolicyConfig:
    close_distance_cm: float = 20.0
    temp_high_c: float = 32.0
    temp_low_c: float = 15.0
    light_low_lux: int = 50
    light_high_lux: int = 900
    light_change_lux: int = 300
    cry_alarm_score_min: int = 60
    tts_cooldown_sec: float = 45.0
    tts_global_cooldown_sec: float = 12.0
    tts_temperature_cooldown_sec: float = 180.0


class CliffDetector:
    """Multi-level cliff detection with debounce hysteresis and IMU-aware direction.

    Escalation is fast (few samples to confirm danger).
    Recovery is slow (many samples to confirm safety).
    """

    def __init__(
        self,
        confirm_samples: int = 2,
        clear_samples: int = 8,
        pitch_down_deg: float = -8.0,
        pitch_up_deg: float = 8.0,
        roll_tilt_deg: float = 10.0,
    ):
        self._confirm_samples = max(1, int(confirm_samples))
        self._clear_samples = max(1, int(clear_samples))
        self._pitch_down_deg = float(pitch_down_deg)
        self._pitch_up_deg = float(pitch_up_deg)
        self._roll_tilt_deg = float(roll_tilt_deg)
        self._level = 0
        self._direction = ""
        self._level_up_count = 0
        self._level_down_count = 0

    @property
    def level(self) -> int:
        return self._level

    @property
    def direction(self) -> str:
        return self._direction

    def update(self, track, imu_packet=None) -> tuple:
        """Feed new sensor readings, return (level, direction) after debounce.

        Args:
            track: list of 4 IR sensor values (0=dark/cliff, 1=ground)
            imu_packet: optional ImuPacket with pitch, roll, healthy fields
        """
        raw = cliff_level(track)

        # Debounce hysteresis
        if raw > self._level:
            self._level_up_count += 1
            self._level_down_count = 0
            if self._level_up_count >= self._confirm_samples:
                self._level = raw
                self._level_up_count = 0
        elif raw < self._level:
            self._level_down_count += 1
            self._level_up_count = 0
            if self._level_down_count >= self._clear_samples:
                self._level = raw
                self._level_down_count = 0
        else:
            self._level_up_count = 0
            self._level_down_count = 0

        # Direction classification (only when sensors indicate potential cliff)
        if self._level >= 1:
            if imu_packet is not None:
                self._direction = cliff_direction(
                    getattr(imu_packet, 'pitch', 0.0),
                    getattr(imu_packet, 'roll', 0.0),
                    getattr(imu_packet, 'healthy', False),
                    pitch_down_deg=self._pitch_down_deg,
                    pitch_up_deg=self._pitch_up_deg,
                    roll_tilt_deg=self._roll_tilt_deg,
                )
            else:
                self._direction = "suspended"
        else:
            self._direction = ""

        return self._level, self._direction


class CarePolicy:
    def __init__(self, config: CarePolicyConfig):
        self.cfg = config
        self._last_lux = None
        self._last_tts_by_token = {}
        self._last_tts_any = None
        self.cliff_detector = CliffDetector(
            confirm_samples=int(os.getenv("RASPBOT_CLIFF_CONFIRM_SAMPLES", "2")),
            clear_samples=int(os.getenv("RASPBOT_CLIFF_CLEAR_SAMPLES", "8")),
            pitch_down_deg=float(os.getenv("RASPBOT_CLIFF_PITCH_DOWN_DEG", "-8.0")),
            pitch_up_deg=float(os.getenv("RASPBOT_CLIFF_PITCH_UP_DEG", "8.0")),
            roll_tilt_deg=float(os.getenv("RASPBOT_CLIFF_ROLL_TILT_DEG", "10.0")),
        )

    @property
    def cliff_level(self) -> int:
        return self.cliff_detector.level

    @property
    def cliff_direction(self) -> str:
        return self.cliff_detector.direction

    def build_alarm_tokens(
        self,
        *,
        env: dict,
        dist_cm: float,
        track: Sequence[int],
        crying: bool,
        cry_score: int,
        undervoltage: bool,
        remote_alarm: str,
        now: float,
        imu: Optional[object] = None,
    ) -> List[str]:
        tokens: List[str] = []
        pcf8591_ok = bool(env.get("pcf8591_ok", True))
        temp_c = _float(env.get("temp_c"), 0.0)
        lux = _int(env.get("light_lux"), 0)

        # Update cliff detector with IMU-aware debounce
        self.cliff_detector.update(track, imu_packet=imu)

        if 0.0 <= float(dist_cm) <= self.cfg.close_distance_cm:
            tokens.append("close_distance")
        if pcf8591_ok and env.get("smoke_alarm"):
            tokens.append("smoke")
        if self.cliff_level >= 3:
            tokens.append("cliff")
        if crying and int(cry_score) >= self.cfg.cry_alarm_score_min:
            tokens.append("cry")
        if undervoltage:
            tokens.append("low_battery")
        if pcf8591_ok:
            if temp_c >= self.cfg.temp_high_c:
                tokens.append("temp_high")
            elif temp_c <= self.cfg.temp_low_c:
                tokens.append("temp_low")
            if lux <= self.cfg.light_low_lux:
                tokens.append("light_low")
            elif lux >= self.cfg.light_high_lux:
                tokens.append("light_high")
            if self._last_lux is not None and abs(lux - self._last_lux) >= self.cfg.light_change_lux:
                tokens.append("light_changed")
            self._last_lux = lux

        for token in _split_alarm_tokens(remote_alarm):
            if token and token not in tokens:
                tokens.append(token)
        return tokens

    def baby_tts_for_tokens(self, tokens: Iterable[str], *, now: float) -> str:
        for token in tokens:
            token = str(token or "").strip().lower()
            text = BABY_TTS_BY_TOKEN.get(token)
            if not text:
                continue
            if self._last_tts_any is not None and now - self._last_tts_any < self.cfg.tts_global_cooldown_sec:
                continue
            last = self._last_tts_by_token.get(token)
            cooldown = self._cooldown_for_token(token)
            if last is not None and now - last < cooldown:
                continue
            self._last_tts_by_token[token] = now
            self._last_tts_any = now
            return text
        return ""

    def _cooldown_for_token(self, token: str) -> float:
        if token in {"temp_high", "temp_low"}:
            return self.cfg.tts_temperature_cooldown_sec
        return self.cfg.tts_cooldown_sec


BABY_TTS_BY_TOKEN = {
    "temp_high": "宝宝乖乖，我们换个舒服一点的地方好不好",
    "temp_low": "宝宝不怕，盖好小被子会暖暖的",
    "light_low": "宝宝，我在这里陪着你哦",
    "light_high": "宝宝，我会慢慢看清楚你",
    "light_changed": "没关系，我慢慢看清楚你",
    "cry": "宝宝别着急，我陪着你呢",
    "cry_detected": "宝宝别着急，我陪着你呢",
    "smoke": "宝宝别怕，我已经叫大人来看你啦",
}


def _split_alarm_tokens(value: str) -> List[str]:
    raw = str(value or "").replace(";", "+").replace(",", "+")
    return [part.strip() for part in raw.split("+") if part.strip()]


def _float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)
