"""Care-oriented alarm and response policy for baby companionship."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

from protocol import is_cliff_track


@dataclass(frozen=True)
class CarePolicyConfig:
    close_distance_cm: float = 20.0
    temp_high_c: float = 32.0
    temp_low_c: float = 18.0
    light_low_lux: int = 50
    light_high_lux: int = 900
    light_change_lux: int = 300
    cry_alarm_score_min: int = 60
    tts_cooldown_sec: float = 45.0
    tts_global_cooldown_sec: float = 12.0
    tts_temperature_cooldown_sec: float = 180.0


class CarePolicy:
    def __init__(self, config: CarePolicyConfig):
        self.cfg = config
        self._last_lux = None
        self._last_tts_by_token = {}
        self._last_tts_any = None

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
    ) -> List[str]:
        tokens: List[str] = []
        temp_c = _float(env.get("temp_c"), 0.0)
        lux = _int(env.get("light_lux"), 0)

        if 0.0 <= float(dist_cm) <= self.cfg.close_distance_cm:
            tokens.append("close_distance")
        if env.get("smoke_alarm"):
            tokens.append("smoke")
        if is_cliff_track(list(track)):
            tokens.append("cliff")
        if crying and int(cry_score) >= self.cfg.cry_alarm_score_min:
            tokens.append("cry")
        if undervoltage:
            tokens.append("low_battery")
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
    "close_distance": "我往后一点点，给宝宝留点空间",
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
