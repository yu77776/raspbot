"""Cloud WebRTC bridge for native App access through signaling/TURN."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Optional

import cv2
import websockets

from .logger_setup import setup_logger
from . import settings as cfg
from .app_gateway import AppGateway, GatewayConfig
from .protocol import (
    TYPE_WEBRTC_ICE,
    TYPE_WEBRTC_OFFER,
    TYPE_WEBRTC_ANSWER,
    payload_has_auth,
    strip_auth_fields,
)
from .voice_cry_bridge import merge_env_cry

logger = setup_logger('raspbot.webrtc')

try:
    from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaStreamTrack
    from aiortc.sdp import candidate_from_sdp, candidate_to_sdp
    from av import VideoFrame
except ImportError:  # pragma: no cover - exercised only on unprepared runtime hosts.
    RTCConfiguration = None
    RTCIceServer = None
    RTCPeerConnection = None
    RTCSessionDescription = None
    MediaStreamTrack = object
    candidate_from_sdp = None
    candidate_to_sdp = None
    VideoFrame = None


@dataclass
class WebRtcBridgeConfig:
    signaling_url: str = "ws://47.108.164.190:8765/pc_room"
    car_host: str = cfg.DEFAULT_CAR_HOST
    car_port: int = cfg.DEFAULT_CAR_PORT
    reconnect_delay: float = 2.0
    stun_url: str = "stun:47.108.164.190:3478"
    turn_url: str = "turn:47.108.164.190:3478"
    turn_username: str = "webrtc_user"
    turn_credential: str = ""
    env_interval: float = 0.2
    video_fps: int = 20
    cry_state: object = None
    auth_token: str = ""


class LatestFrameVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, frame_provider: Callable[[], tuple]):
        super().__init__()
        self._frame_provider = frame_provider
        self._seq = -1
        self._start = time.monotonic()
        self._pts = 0
        self._time_base = Fraction(1, 90000)

    async def recv(self):
        if VideoFrame is None:
            raise RuntimeError("aiortc/av is not installed")

        frame = None
        for _ in range(80):
            frame, seq = self._frame_provider()
            if frame is not None and seq != self._seq:
                self._seq = seq
                break
            await asyncio.sleep(0.01)

        if frame is None:
            frame = _blank_frame()

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(rgb, format="rgb24")
        now = time.monotonic()
        self._pts = int((now - self._start) * 90000)
        video_frame.pts = self._pts
        video_frame.time_base = self._time_base
        return video_frame


def _blank_frame():
    import numpy as np

    frame = np.zeros((cfg.FRAME_H, cfg.FRAME_W, 3), dtype=np.uint8)
    cv2.putText(
        frame,
        "Waiting for Raspbot video...",
        (80, cfg.FRAME_H // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (220, 220, 220),
        2,
    )
    return frame


class WebRtcBridge:
    def __init__(self, cfg_: WebRtcBridgeConfig, frame_provider: Callable[[], tuple], env_provider: Callable[[], dict]):
        if RTCPeerConnection is None:
            raise RuntimeError("aiortc is required: run `python -m pip install aiortc` in the PC environment")
        self.cfg = cfg_
        self._frame_provider = frame_provider
        self._env_provider = env_provider
        self._gateway = AppGateway(
            GatewayConfig(
                car_host=cfg_.car_host,
                car_port=cfg_.car_port,
                reconnect_delay=cfg_.reconnect_delay,
                cry_state=cfg_.cry_state,
                auth_token=cfg_.auth_token,
            )
        )
        self._pc: Optional[RTCPeerConnection] = None
        self._env_channel = None
        self._command_channel = None
        self._pending_ice = []
        self._stop_event: Optional[threading.Event] = None
        self._env_task: Optional[asyncio.Task] = None

    async def run(self, stop_event: Optional[threading.Event] = None):
        self._stop_event = stop_event or threading.Event()
        self._install_aiortc_exception_filter()
        car_task = asyncio.create_task(self._gateway._car_loop(self._stop_event))
        try:
            while not self._stop_event.is_set():
                try:
                    await self._signaling_session()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning('disconnected: %s', exc)
                await self._close_peer()
                if not self._stop_event.is_set():
                    await asyncio.sleep(self.cfg.reconnect_delay)
        finally:
            await self._close_peer()
            car_task.cancel()
            await asyncio.gather(car_task, return_exceptions=True)

    async def _signaling_session(self):
        logger.info('signaling connect %s', self.cfg.signaling_url)
        async with websockets.connect(
            self.cfg.signaling_url,
            max_size=10 * 1024 * 1024,
            open_timeout=8,
            proxy=None,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=2,
        ) as ws:
            logger.info('signaling connected')
            await self._create_peer(ws)
            while self._stop_event is None or not self._stop_event.is_set():
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if isinstance(message, bytes):
                    continue
                await self._handle_signal(ws, message)

    async def _create_peer(self, ws):
        await self._close_peer()
        ice_servers = [RTCIceServer(urls=self.cfg.stun_url)]
        if self.cfg.turn_url and self.cfg.turn_username and self.cfg.turn_credential:
            ice_servers.append(
                RTCIceServer(
                    urls=self.cfg.turn_url,
                    username=self.cfg.turn_username,
                    credential=self.cfg.turn_credential,
                )
            )
        pc = RTCPeerConnection(RTCConfiguration(iceServers=ice_servers))
        self._pc = pc
        pc.addTrack(LatestFrameVideoTrack(self._frame_provider))
        self._env_channel = pc.createDataChannel("env")
        self._command_channel = pc.createDataChannel("command")
        self._command_channel.on("message", lambda message: asyncio.create_task(self._handle_command_message(message)))

        @pc.on("datachannel")
        def on_datachannel(channel):
            if channel.label == "env":
                self._env_channel = channel
            elif channel.label == "command":
                self._command_channel = channel
                channel.on("message", lambda message: asyncio.create_task(self._handle_command_message(message)))

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate is None:
                return
            await ws.send(json.dumps({"type": TYPE_WEBRTC_ICE, "candidate": _candidate_to_json(candidate)}))

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if self._pc is pc:
                logger.info('peer connection %s', pc.connectionState)
                if pc.connectionState in {"failed", "closed", "disconnected"}:
                    asyncio.create_task(self._close_peer(pc))

        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            if self._pc is pc:
                logger.info('peer ice %s', pc.iceConnectionState)
                if pc.iceConnectionState in {"failed", "closed", "disconnected"}:
                    asyncio.create_task(self._close_peer(pc))

        self._env_task = asyncio.create_task(self._env_loop(pc))

    async def _handle_signal(self, ws, message: str):
        try:
            payload = json.loads(message)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        msg_type = str(payload.get("type", "") or "").lower()
        if msg_type == TYPE_WEBRTC_OFFER:
            if not payload_has_auth(payload, self.cfg.auth_token):
                logger.warning('drop unauthorized WebRTC offer')
                return
            await self._accept_offer(ws, payload)
        elif msg_type == TYPE_WEBRTC_ICE:
            if not payload_has_auth(payload, self.cfg.auth_token):
                logger.warning('drop unauthorized WebRTC ice')
                return
            await self._add_ice(payload)
        elif msg_type in {"ping", "join", "joined"}:
            return

    async def _accept_offer(self, ws, payload: dict):
        sdp = str(payload.get("sdp") or payload.get("offer") or "").replace("\\n", "\n")
        if not sdp:
            return
        await self._create_peer(ws)
        pc = self._pc
        if pc is None:
            return
        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
        for candidate in list(self._pending_ice):
            await pc.addIceCandidate(candidate)
        self._pending_ice.clear()
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await ws.send(
            json.dumps(
                {
                    "type": TYPE_WEBRTC_ANSWER,
                    "sdp": pc.localDescription.sdp,
                    "sdpType": pc.localDescription.type,
                }
            )
        )
        logger.info('answered app offer')

    async def _add_ice(self, payload: dict):
        candidate = _candidate_from_payload(payload)
        if candidate is None:
            return
        pc = self._pc
        if pc is None or pc.remoteDescription is None:
            self._pending_ice.append(candidate)
            return
        await pc.addIceCandidate(candidate)

    async def _handle_command_message(self, message):
        payload = self._command_payload_from_message(message)
        if payload is None:
            return
        await self._gateway._send_to_car(payload)

    def _command_payload_from_message(self, message):
        if isinstance(message, bytes):
            if len(message) < 2 or message[0] != cfg.MSG_COMMAND:
                return None
            try:
                payload = json.loads(message[1:].decode("utf-8"))
            except Exception:
                return None if self.cfg.auth_token else message
            if not payload_has_auth(payload, self.cfg.auth_token):
                logger.warning('drop unauthorized WebRTC command')
                return None
            return bytes([cfg.MSG_COMMAND]) + json.dumps(strip_auth_fields(payload), ensure_ascii=False).encode("utf-8")

        text = str(message)
        try:
            payload = json.loads(text)
        except Exception:
            if self.cfg.auth_token:
                logger.warning('drop non-json WebRTC command while auth is required')
                return None
            return bytes([cfg.MSG_COMMAND]) + text.encode("utf-8")
        if not isinstance(payload, dict):
            return None
        if not payload_has_auth(payload, self.cfg.auth_token):
            logger.warning('drop unauthorized WebRTC command')
            return None

        voice_cmd = self._gateway._build_voice_command_from_obj(payload)
        if voice_cmd is not None:
            return voice_cmd
        return bytes([cfg.MSG_COMMAND]) + json.dumps(strip_auth_fields(payload), ensure_ascii=False).encode("utf-8")

    def _install_aiortc_exception_filter(self):
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()

        def handler(loop_, context):
            if _is_aiortc_disconnect_noise(context):
                logger.debug("suppressed aiortc disconnect noise: %s", context.get("exception"))
                return
            if previous_handler is not None:
                previous_handler(loop_, context)
            else:
                loop_.default_exception_handler(context)

        loop.set_exception_handler(handler)

    async def _env_loop(self, pc):
        last_sent = ""
        while self._pc is pc:
            if pc.connectionState in {"failed", "closed", "disconnected"}:
                break
            if pc.iceConnectionState in {"failed", "closed", "disconnected"}:
                break
            channel = self._env_channel
            if channel is not None and channel.readyState == "open":
                payload = self._env_provider() or {}
                payload = self._merge_env_cry(payload)
                text = json.dumps(payload, ensure_ascii=False)
                if text != last_sent:
                    try:
                        channel.send(text)
                        last_sent = text
                    except Exception:
                        pass
            await asyncio.sleep(max(0.05, float(self.cfg.env_interval)))

    def _merge_env_cry(self, payload: dict) -> dict:
        if self.cfg.cry_state is None or not isinstance(payload, dict):
            return payload
        return merge_env_cry(payload, self.cfg.cry_state)

    async def _close_peer(self, pc=None):
        target = pc or self._pc
        if target is None:
            return
        if self._pc is target:
            self._pc = None
            self._env_channel = None
            self._command_channel = None
            self._pending_ice.clear()
            env_task = self._env_task
            self._env_task = None
            if (
                env_task is not None
                and not env_task.done()
                and env_task is not asyncio.current_task()
            ):
                env_task.cancel()
                await asyncio.gather(env_task, return_exceptions=True)
        await target.close()


def _is_aiortc_disconnect_noise(context: dict) -> bool:
    exc = context.get("exception")
    return isinstance(exc, ConnectionError) and "Cannot send data, not connected" in str(exc)


def _candidate_to_json(candidate) -> dict:
    return {
        "candidate": "candidate:" + candidate_to_sdp(candidate),
        "sdpMid": candidate.sdpMid,
        "sdpMLineIndex": candidate.sdpMLineIndex,
    }


def _candidate_from_payload(payload: dict):
    candidate_obj = payload.get("candidate")
    if isinstance(candidate_obj, dict):
        candidate_sdp = str(candidate_obj.get("candidate") or "")
        sdp_mid = candidate_obj.get("sdpMid")
        sdp_mline_index = candidate_obj.get("sdpMLineIndex")
    else:
        candidate_sdp = str(candidate_obj or payload.get("ice") or "")
        sdp_mid = payload.get("sdpMid")
        sdp_mline_index = payload.get("sdpMLineIndex")
    if not candidate_sdp:
        return None
    if candidate_sdp.startswith("candidate:"):
        candidate_sdp = candidate_sdp[len("candidate:") :]
    candidate = candidate_from_sdp(candidate_sdp)
    candidate.sdpMid = sdp_mid
    candidate.sdpMLineIndex = int(sdp_mline_index or 0)
    return candidate


def parse_args():
    p = argparse.ArgumentParser(description="Raspbot cloud WebRTC bridge")
    p.add_argument("--signaling-url", default=os.getenv("RASPBOT_WEBRTC_SIGNALING_URL", "ws://47.108.164.190:8765/pc_room"))
    p.add_argument("--car-host", default=os.getenv("RASPBOT_CAR_IP", os.getenv("CAR_HOST", cfg.DEFAULT_CAR_HOST)))
    p.add_argument("--car-port", type=int, default=int(os.getenv("RASPBOT_CAR_PORT", str(cfg.DEFAULT_CAR_PORT))))
    p.add_argument("--turn-credential", default=os.getenv("RASPBOT_TURN_CREDENTIAL", ""))
    p.add_argument("--auth-token", default=os.getenv("RASPBOT_AUTH_TOKEN", ""))
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit("Start this bridge through pc_modules.app so it can use processed YOLO frames.")
