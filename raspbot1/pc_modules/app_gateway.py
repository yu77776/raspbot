"""PC-side App gateway: App(7000) <-> Car(5001) using existing packet stream."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Optional, Set

import websockets

from . import settings as cfg
from .packets import CommandPacket
from .protocol import TYPE_APP_VOICE
from .voice_cry_bridge import CryStateStore, parse_voice_intent

logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
logging.getLogger("websockets.asyncio.server").setLevel(logging.CRITICAL)


def _safe_ws_path(ws) -> str:
    path = getattr(ws, "path", None)
    if path:
        return path
    req = getattr(ws, "request", None)
    if req is not None:
        return getattr(req, "path", "") or ""
    return ""


@dataclass
class GatewayConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 7000
    car_host: str = cfg.DEFAULT_CAR_HOST
    car_port: int = cfg.DEFAULT_CAR_PORT
    reconnect_delay: float = 1.5
    cry_state: Optional[CryStateStore] = None

    @property
    def car_uri(self) -> str:
        return f"ws://{self.car_host}:{self.car_port}"


class AppGateway:
    """Bridge App commands to car and car env packets back to App."""

    def __init__(self, cfg_: GatewayConfig):
        self.cfg = cfg_
        self._cry_state = cfg_.cry_state
        self._clients: Set[object] = set()
        self._clients_lock = asyncio.Lock()
        self._car_ws = None
        self._car_send_lock = asyncio.Lock()
        self._car_ready = asyncio.Event()

    async def _add_client(self, ws):
        async with self._clients_lock:
            self._clients.add(ws)

    async def _drop_client(self, ws):
        async with self._clients_lock:
            self._clients.discard(ws)

    async def _broadcast_to_apps(self, payload: bytes):
        async with self._clients_lock:
            clients = list(self._clients)
        if not clients:
            return
        closed = []
        for client in clients:
            try:
                await client.send(payload)
            except Exception:
                closed.append(client)
        if closed:
            async with self._clients_lock:
                for client in closed:
                    self._clients.discard(client)

    async def _send_to_car(self, payload: bytes):
        if not self._car_ready.is_set():
            return
        payload = self._merge_command_cry(payload)
        async with self._car_send_lock:
            ws = self._car_ws
            if ws is None:
                return
            await ws.send(payload)

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
                    print(f"[APPGW] car connected: {self.cfg.car_uri}")
                    async for message in car_ws:
                        if isinstance(message, str):
                            await self._broadcast_to_apps(message)
                            continue
                        if not isinstance(message, bytes) or len(message) < 2:
                            continue
                        if message[0] not in (cfg.MSG_ENV, cfg.MSG_VIDEO):
                            continue
                        if message[0] == cfg.MSG_ENV:
                            await self._broadcast_to_apps(self._merge_env_cry(message))
                        else:
                            await self._broadcast_to_apps(message)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[APPGW] car disconnected: {exc}")
            finally:
                self._car_ws = None
                self._car_ready.clear()
            if not stop_event.is_set():
                await asyncio.sleep(self.cfg.reconnect_delay)

    async def handle_app(self, ws):
        path = _safe_ws_path(ws) or "/"
        peer = getattr(ws, "remote_address", None)
        await self._add_client(ws)
        print(f"[APPGW] app connected: {peer} path={path}")
        try:
            async for message in ws:
                if isinstance(message, str):
                    voice_cmd = self._build_voice_command_from_app_text(message)
                    if voice_cmd is not None:
                        await self._send_to_car(voice_cmd)
                    elif self._is_app_voice_json(message):
                        print("[APPGW] app_voice ignored: no matched intent")
                    else:
                        await self._send_to_car(message)
                    continue
                if not isinstance(message, bytes) or len(message) < 2:
                    continue
                if message[0] != cfg.MSG_COMMAND:
                    continue
                await self._send_to_car(message)
        except websockets.ConnectionClosed:
            pass
        finally:
            await self._drop_client(ws)
            print(f"[APPGW] app disconnected: {peer}")

    async def run(self, stop_event: Optional[threading.Event] = None):
        print(
            f"[APPGW] listen ws://{self.cfg.listen_host}:{self.cfg.listen_port} "
            f"-> {self.cfg.car_uri} (0x02 => car, 0x01/0x03 => app)"
        )
        local_stop = stop_event or threading.Event()
        car_task = asyncio.create_task(self._car_loop(local_stop))
        try:
            async with websockets.serve(
                self.handle_app,
                self.cfg.listen_host,
                self.cfg.listen_port,
                max_size=10 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=10,
            ):
                while not local_stop.is_set():
                    await asyncio.sleep(0.2)
        finally:
            car_task.cancel()
            await asyncio.gather(car_task, return_exceptions=True)

    def _build_voice_command_from_app_text(self, text_message: str) -> Optional[bytes]:
        try:
            payload = json.loads(text_message)
        except Exception:
            return None
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
        print(
            f"[APPGW] app_voice text={voice_text!r} -> action={cmd.action} "
            f"song={cmd.play_song!r} stop_audio={cmd.stop_audio}"
        )
        return bytes([cfg.MSG_COMMAND]) + json.dumps(cmd.to_wire_dict()).encode("utf-8")

    def _is_app_voice_json(self, text_message: str) -> bool:
        try:
            payload = json.loads(text_message)
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        msg_type = str(payload.get("type", "") or "").strip().lower()
        action = str(payload.get("action", "") or "").strip().lower()
        return msg_type == TYPE_APP_VOICE or action in {"voice", TYPE_APP_VOICE}

    def _merge_command_cry(self, command_packet):
        if self._cry_state is None:
            return command_packet
        if not isinstance(command_packet, (bytes, bytearray)) or len(command_packet) < 2:
            return command_packet
        if command_packet[0] != cfg.MSG_COMMAND:
            return command_packet
        try:
            payload = json.loads(bytes(command_packet[1:]).decode("utf-8"))
        except Exception:
            return command_packet
        if not isinstance(payload, dict):
            return command_packet

        cry = self._cry_state.snapshot()
        payload["remote_crying"] = bool(cry.crying)
        payload["remote_cry_score"] = int(cry.cry_score)
        payload["remote_alarm"] = str(cry.alarm or "")
        return bytes([cfg.MSG_COMMAND]) + json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _merge_env_cry(self, env_packet: bytes) -> bytes:
        if self._cry_state is None:
            return env_packet
        try:
            payload = json.loads(env_packet[1:].decode("utf-8"))
        except Exception:
            return env_packet
        if not isinstance(payload, dict):
            return env_packet

        cry = self._cry_state.snapshot()
        payload["crying"] = bool(cry.crying)
        payload["cry_score"] = int(cry.cry_score)

        base_alarm = str(payload.get("alarm", "") or "").strip()
        if cry.alarm:
            if not base_alarm:
                payload["alarm"] = cry.alarm
            elif cry.alarm not in base_alarm:
                payload["alarm"] = f"{base_alarm}; {cry.alarm}"

        return bytes([cfg.MSG_ENV]) + json.dumps(payload, ensure_ascii=False).encode("utf-8")


class AppGatewayRunner:
    """Run AppGateway in a background thread."""

    def __init__(self, cfg_: GatewayConfig):
        self.cfg = cfg_
        self._gateway = AppGateway(cfg_)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[Exception] = None

    def _run(self):
        try:
            asyncio.run(self._gateway.run(stop_event=self._stop_event))
        except Exception as exc:
            self._error = exc
            print(f"[APPGW] server thread error: {exc}")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    @property
    def error(self) -> Optional[Exception]:
        return self._error


def parse_args():
    p = argparse.ArgumentParser(description="Raspbot App gateway")
    p.add_argument("--listen-host", default=os.getenv("APP_GATEWAY_HOST", "0.0.0.0"))
    p.add_argument("--listen-port", type=int, default=int(os.getenv("APP_GATEWAY_PORT", "7000")))
    p.add_argument("--car-host", default=os.getenv("RASPBOT_CAR_IP", os.getenv("CAR_HOST", cfg.DEFAULT_CAR_HOST)))
    p.add_argument("--car-port", type=int, default=int(os.getenv("RASPBOT_CAR_PORT", str(cfg.DEFAULT_CAR_PORT))))
    p.add_argument("--reconnect-delay", type=float, default=float(os.getenv("APP_GATEWAY_RECONNECT_DELAY", "1.5")))
    return p.parse_args()


def main():
    args = parse_args()
    cfg_ = GatewayConfig(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        car_host=args.car_host,
        car_port=args.car_port,
        reconnect_delay=args.reconnect_delay,
    )
    asyncio.run(AppGateway(cfg_).run())


if __name__ == "__main__":
    main()
