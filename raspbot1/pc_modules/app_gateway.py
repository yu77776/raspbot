"""Shared App command adapter used by the cloud WebRTC bridge."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from typing import Optional

import websockets

from . import settings as cfg
from .logger_setup import setup_logger
from .packets import CommandPacket
from .protocol import (
    TYPE_APP_VOICE,
    append_auth_token_to_uri,
    strip_auth_fields,
)
from .voice_cry_bridge import CryStateStore, parse_voice_intent

logger = setup_logger('raspbot.appgw')


class TrackingModeStore:
    def __init__(self, enabled: bool = True):
        self._enabled = bool(enabled)
        self._lock = threading.Lock()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)

    def is_enabled(self) -> bool:
        with self._lock:
            return bool(self._enabled)


@dataclass
class GatewayConfig:
    car_host: str = cfg.DEFAULT_CAR_HOST
    car_port: int = cfg.DEFAULT_CAR_PORT
    reconnect_delay: float = 1.5
    cry_state: Optional[CryStateStore] = None
    auth_token: str = ""
    tracking_mode_store: Optional[TrackingModeStore] = None

    @property
    def car_uri(self) -> str:
        return append_auth_token_to_uri(f"ws://{self.car_host}:{self.car_port}", self.auth_token)


def _try_decode_command(packet) -> Optional[dict]:
    """Decode a MSG_COMMAND binary packet to a JSON dict, or return None."""
    if not isinstance(packet, (bytes, bytearray)) or len(packet) < 2:
        return None
    if packet[0] != cfg.MSG_COMMAND:
        return None
    try:
        payload = json.loads(bytes(packet[1:]).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


class AppGateway:
    """Bridge WebRTC App commands to the car packet stream."""

    def __init__(self, cfg_: GatewayConfig):
        self.cfg = cfg_
        self._cry_state = cfg_.cry_state
        self._car_ws = None
        self._car_send_lock = asyncio.Lock()
        self._car_ready = asyncio.Event()
        self._last_merged_cry: Optional[tuple] = None
        self._tracking_mode_store = cfg_.tracking_mode_store or TrackingModeStore(enabled=True)

    async def _send_to_car(self, payload: bytes):
        tracking_mode = self._extract_tracking_mode(payload)
        if tracking_mode is not None:
            self._tracking_mode_store.set_enabled(tracking_mode)
            logger.info('app tracking_mode=%s', self._tracking_mode_store.is_enabled())
            if self._is_app_auto_status_payload(payload):
                return
        payload = self._strip_command_auth(payload)
        payload = self._merge_command_cry(payload)
        async with self._car_send_lock:
            if not self._car_ready.is_set():
                return
            ws = self._car_ws
            if ws is None:
                return
            try:
                await ws.send(payload)
            except Exception as exc:
                self._car_ready.clear()
                self._car_ws = None
                logger.warning('drop app command; car send failed: %s', exc)

    async def _cry_state_sync_loop(self, car_ws):
        if self._cry_state is None:
            return
        while True:
            payload = bytes([cfg.MSG_COMMAND]) + json.dumps({"source": "cry_sync"}).encode("utf-8")
            payload = self._merge_command_cry(payload)
            await car_ws.send(payload)
            await asyncio.sleep(0.5)

    def _strip_command_auth(self, command_packet):
        payload = _try_decode_command(command_packet)
        if payload is None:
            return command_packet
        return bytes([cfg.MSG_COMMAND]) + json.dumps(strip_auth_fields(payload), ensure_ascii=False).encode("utf-8")

    def _extract_tracking_mode(self, command_packet) -> Optional[bool]:
        payload = _try_decode_command(command_packet)
        if payload is None or "tracking_mode" not in payload:
            return None
        return CommandPacket.from_dict(payload).tracking_mode

    def _is_app_auto_status_payload(self, command_packet) -> bool:
        """True when this is a pure tracking-mode keepalive with no actionable content.

        A payload is *not* a status-only keepalive when it carries audio_volume,
        an explicit motion action, or other fields the car should act on.
        """
        payload = _try_decode_command(command_packet)
        if payload is None:
            return False
        if str(payload.get("source", "") or "").strip().lower() != "app_auto":
            return False
        if not bool(CommandPacket.from_dict(payload).tracking_mode):
            return False
        # Don't drop when there's something actionable for the car.
        if "audio_volume" in payload:
            return False
        return True

    def is_tracking_enabled(self) -> bool:
        return self._tracking_mode_store.is_enabled()

    async def _car_loop(self, stop_event: threading.Event):
        while not stop_event.is_set():
            try:
                async with websockets.connect(
                    self.cfg.car_uri,
                    max_size=10 * 1024 * 1024,
                    open_timeout=8,
                    proxy=None,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=2,
                ) as car_ws:
                    self._car_ws = car_ws
                    self._car_ready.set()
                    logger.info('car connected: %s', self.cfg.car_uri)
                    sync_task = asyncio.create_task(self._cry_state_sync_loop(car_ws))
                    try:
                        async for message in car_ws:
                            # The WebRTC bridge uses its own PCClientWS instance for
                            # video/env data. This adapter still has to continuously
                            # drain the car socket so the command channel stays healthy.
                            continue
                    finally:
                        sync_task.cancel()
                        await asyncio.gather(sync_task, return_exceptions=True)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning('car disconnected: %s', exc)
            finally:
                self._car_ws = None
                self._car_ready.clear()
            if not stop_event.is_set():
                await asyncio.sleep(self.cfg.reconnect_delay)

    def _build_voice_command_from_obj(self, payload: dict) -> Optional[bytes]:
        if not isinstance(payload, dict):
            return None

        msg_type = str(payload.get("type", "") or "").strip().lower()
        action = str(payload.get("action", "") or "").strip().lower()
        if msg_type != TYPE_APP_VOICE and action not in {"voice", TYPE_APP_VOICE}:
            return None
        voice_text = str(payload.get("text", payload.get("command", "")) or "")
        intent = parse_voice_intent(voice_text)
        if not intent:
            return None

        move_action = str(intent.get("action", "stop") or "stop")
        speed = cfg.MOTOR_SPEED if move_action != "stop" else 0
        cmd = CommandPacket(
            action=move_action,
            servo_angle=90.0,
            servo_angle2=90.0,
            speed=speed,
            left_speed=speed,
            right_speed=speed,
            detecting=False,
            play_song=str(intent.get("play_song", "") or ""),
            stop_audio=bool(intent.get("stop_audio", False)),
        )
        logger.info('app_voice text=%s -> action=%s song=%s stop_audio=%s', voice_text, cmd.action, cmd.play_song, cmd.stop_audio)
        return bytes([cfg.MSG_COMMAND]) + json.dumps(cmd.to_wire_dict()).encode("utf-8")

    def _merge_command_cry(self, command_packet):
        if self._cry_state is None:
            return command_packet
        payload = _try_decode_command(command_packet)
        if payload is None:
            return command_packet
        payload = strip_auth_fields(payload)

        cry = self._cry_state.snapshot()
        new_cry = (bool(cry.crying), int(cry.cry_score), str(cry.alarm or ""))
        # Skip re-serialization when cry state is unchanged and payload already matches.
        if new_cry == self._last_merged_cry:
            if (payload.get("remote_crying") == new_cry[0]
                    and payload.get("remote_cry_score") == new_cry[1]
                    and payload.get("remote_alarm") == new_cry[2]):
                return command_packet
        self._last_merged_cry = new_cry
        payload["remote_crying"] = new_cry[0]
        payload["remote_cry_score"] = new_cry[1]
        payload["remote_alarm"] = new_cry[2]
        return bytes([cfg.MSG_COMMAND]) + json.dumps(payload, ensure_ascii=False).encode("utf-8")
