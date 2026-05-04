"""Shared voice-intent parsing and cry-state bridge for PC modules."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from . import settings as cfg
from .protocol import PLAY_SONG_NEXT, PLAY_SONG_PREV


def _intent(action="stop", *, play_song="", stop_audio=False, audio_volume=None,
            hold=1.2, one_shot=True):
    return {
        "action": action,
        "play_song": play_song,
        "stop_audio": stop_audio,
        "audio_volume": audio_volume,
        "hold": hold,
        "one_shot": one_shot,
    }


def parse_voice_intent(text: str, hold_sec: float = 2.2) -> Optional[Dict[str, object]]:
    cleaned = re.sub(r"\s+", "", (text or "").lower())
    if not cleaned:
        return None

    stop_audio_keys = [
        "停止播放",
        "暂停播放",
        "停歌",
        "别唱了",
        "停止音乐",
        "关闭音乐",
    ]
    play_audio_keys = [
        "播放儿歌",
        "放儿歌",
        "播放音乐",
        "放音乐",
        "唱歌",
    ]
    next_audio_keys = [
        "下一首",
        "下首",
        "换一首",
        "切歌",
        "换歌",
    ]
    prev_audio_keys = [
        "上一首",
        "上首",
        "前一首",
    ]
    if any(k in cleaned for k in stop_audio_keys):
        return _intent(stop_audio=True, audio_volume=None)

    if any(k in cleaned for k in next_audio_keys):
        return _intent(play_song=PLAY_SONG_NEXT, audio_volume=cfg.VOICE_DEFAULT_AUDIO_VOLUME)

    if any(k in cleaned for k in prev_audio_keys):
        return _intent(play_song=PLAY_SONG_PREV, audio_volume=cfg.VOICE_DEFAULT_AUDIO_VOLUME)

    if any(k in cleaned for k in play_audio_keys):
        return _intent(play_song=cfg.VOICE_DEFAULT_SONG_FILE, audio_volume=cfg.VOICE_DEFAULT_AUDIO_VOLUME)

    action = None
    stop_keys = ["停止", "停下", "停车", "别动", "不要动", "等等"]
    forward_keys = ["前进", "向前", "往前"]
    backward_keys = ["后退", "向后", "往后"]
    left_keys = ["左转", "向左", "往左"]
    right_keys = ["右转", "向右", "往右"]

    if any(k in cleaned for k in stop_keys):
        action = "stop"
    elif any(k in cleaned for k in forward_keys):
        action = "forward"
    elif any(k in cleaned for k in backward_keys):
        action = "backward"
    elif any(k in cleaned for k in left_keys):
        action = "spin_left"
    elif any(k in cleaned for k in right_keys):
        action = "spin_right"
    elif "右" in cleaned and "转" in cleaned:
        action = "spin_right"
    elif "左" in cleaned and "转" in cleaned:
        action = "spin_left"

    if not action:
        return None

    return _intent(action=action, hold=1.5 if action == "stop" else hold_sec, one_shot=False)


def merge_env_cry(payload: dict, cry_state) -> dict:
    """Merge cry state into an env payload dict. Used by both app_gateway and webrtc_bridge."""
    merged = dict(payload)
    cry = cry_state.snapshot()
    merged["crying"] = bool(cry.crying)
    merged["cry_score"] = int(cry.cry_score)
    base_alarm = str(merged.get("alarm", "") or "").strip()
    if cry.alarm:
        if not base_alarm:
            merged["alarm"] = cry.alarm
        elif cry.alarm not in base_alarm:
            merged["alarm"] = f"{base_alarm}; {cry.alarm}"
    return merged


@dataclass(frozen=True)
class CrySnapshot:
    crying: bool
    cry_score: int
    alarm: str
    updated_at: float


class CryStateStore:
    """Thread-safe cry-state storage shared across ASR and app gateway threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._crying = False
        self._cry_score = 0
        self._alarm = ""
        self._updated_at = 0.0

    def update_from_ratio(self, is_crying: bool, ratio: float) -> None:
        score = int(max(0, min(100, round(float(ratio) * 100.0))))
        alarm = f"cry_detected score={score}" if is_crying else ""
        now = time.monotonic()
        with self._lock:
            self._crying = bool(is_crying)
            self._cry_score = score
            self._alarm = alarm
            self._updated_at = now

    def snapshot(self) -> CrySnapshot:
        with self._lock:
            return CrySnapshot(
                crying=self._crying,
                cry_score=self._cry_score,
                alarm=self._alarm,
                updated_at=self._updated_at,
            )
