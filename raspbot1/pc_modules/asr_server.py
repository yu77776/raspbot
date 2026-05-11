"""Minimal Baidu realtime ASR WebSocket server.

Receives PCM 16kHz/16bit/mono audio from clients and transcribes via Baidu.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import websockets
from websockets.exceptions import ConnectionClosed

from .local_env import load_baidu_asr_config
from .logger_setup import setup_logger
from .protocol import _safe_ws_path

logger = setup_logger("raspbot.asr")

SAMPLE_RATE = 16000


# ═══════════════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 6006
    path: str = "/audio"
    # Baidu credentials
    baidu_api_key: str = ""
    baidu_secret_key: str = ""
    baidu_access_token: str = ""
    baidu_url: str = "wss://vop.baidu.com/realtime_asr"
    baidu_dev_pid: int = 15372
    baidu_cuid: str = "raspbot-pc"
    baidu_frame_ms: int = 160
    # Callback
    on_text: Optional[Callable[[str], None]] = None
    # ── deprecated, kept for caller compatibility ──
    sample_rate: int = SAMPLE_RATE
    window_sec: float = 3.0
    step_sec: float = 1.5
    silence_rms: int = 150
    baidu_appid: str = ""
    baidu_lm_id: str = ""
    baidu_user: str = ""
    baidu_emit_partial: bool = False
    on_cry_state: Optional[Callable] = None
    cry_detector_factory: Optional[Callable[[], object]] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Baidu ASR helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_access_token(api_key: str, secret_key: str, cached_token: str = "") -> str:
    if cached_token:
        return cached_token
    if not api_key or not secret_key:
        raise RuntimeError("BAIDU_API_KEY and BAIDU_SECRET_KEY are required")
    params = urlencode({
        "grant_type": "client_credentials",
        "client_id": api_key,
        "client_secret": secret_key,
    })
    req = Request(
        f"https://aip.baidubce.com/oauth/2.0/token?{params}",
        data=b"",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    token = str(body.get("access_token", "")).strip()
    if not token:
        raise RuntimeError(f"Baidu token response missing access_token: {body}")
    return token


def _build_baidu_url(base_url: str, token: str) -> str:
    parts = urlsplit(base_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["sn"] = str(uuid.uuid4())
    params["token"] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _pick_config_value(cfg_value, env_key: str, local: dict, local_key: str, default=""):
    value = cfg_value or os.getenv(env_key, "") or local.get(local_key, default)
    return str(value).strip() if value is not None else str(default)


def _coerce_baidu_appid(value: str):
    value = str(value or "").strip()
    if not value:
        return None
    if not value.isdigit():
        raise RuntimeError(f"BAIDU_APPID must be numeric, got {value!r}")
    return int(value)


def _build_start_frame(dev_pid: int, cuid: str, appid: str = "", appkey: str = "") -> str:
    data = {
        "dev_pid": dev_pid,
        "cuid": cuid,
        "format": "pcm",
        "sample": SAMPLE_RATE,
    }
    coerced_appid = _coerce_baidu_appid(appid)
    if coerced_appid is not None:
        data["appid"] = coerced_appid
    if appkey:
        data["appkey"] = str(appkey)
    return json.dumps({"type": "START", "data": data}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Server
# ═══════════════════════════════════════════════════════════════════════════════

class AsrServer:
    """WS server bridging client PCM audio → Baidu realtime ASR."""

    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self._frame_bytes = int(SAMPLE_RATE * 2 * max(20, min(200, int(cfg.baidu_frame_ms))) / 1000)
        self._access_token: Optional[str] = None
        self._baidu_local_config: Optional[dict] = None
        self._cry_detector = None
        self._cry_detector_failed = False

    def _emit_text(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        logger.info("[%s] %s", time.strftime("%H:%M:%S"), text)
        if self.cfg.on_text:
            try:
                self.cfg.on_text(text)
            except Exception as exc:
                logger.warning("on_text error: %s", exc)

    def _get_cry_detector(self):
        if self.cfg.on_cry_state is None:
            return None
        if self._cry_detector is not None:
            return self._cry_detector
        if self._cry_detector_failed:
            return None
        try:
            if self.cfg.cry_detector_factory is not None:
                self._cry_detector = self.cfg.cry_detector_factory()
            else:
                from .cry_detector import YamnetCryDetector

                self._cry_detector = YamnetCryDetector()
            return self._cry_detector
        except Exception as exc:
            self._cry_detector_failed = True
            logger.warning("cry detector init failed: %s", exc)
            return None

    def _feed_cry_detector(self, audio: bytes) -> None:
        detector = self._get_cry_detector()
        if detector is None:
            return
        try:
            updates = detector.feed_pcm16(audio)
            for crying, ratio in updates:
                self.cfg.on_cry_state(bool(crying), float(ratio))
        except Exception as exc:
            logger.warning("cry detector update failed: %s", exc)

    async def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        local = await self._get_baidu_local_config()
        api_key = _pick_config_value(self.cfg.baidu_api_key, "BAIDU_API_KEY", local, "api_key")
        secret_key = _pick_config_value(self.cfg.baidu_secret_key, "BAIDU_SECRET_KEY", local, "secret_key")
        cached = _pick_config_value(self.cfg.baidu_access_token, "BAIDU_ACCESS_TOKEN", local, "access_token")
        token = await asyncio.to_thread(_fetch_access_token, api_key, secret_key, cached)
        self._access_token = token
        return token

    async def _get_baidu_local_config(self) -> dict:
        if self._baidu_local_config is None:
            self._baidu_local_config = await asyncio.to_thread(load_baidu_asr_config)
        return self._baidu_local_config

    async def _build_start_frame(self) -> str:
        local = await self._get_baidu_local_config()
        appid = _pick_config_value(self.cfg.baidu_appid, "BAIDU_APPID", local, "appid")
        api_key = _pick_config_value(self.cfg.baidu_api_key, "BAIDU_API_KEY", local, "api_key")
        cuid = _pick_config_value(self.cfg.baidu_cuid, "BAIDU_CUID", local, "cuid", "raspbot-pc")
        dev_pid_raw = _pick_config_value(self.cfg.baidu_dev_pid, "BAIDU_DEV_PID", local, "dev_pid", 15372)
        return _build_start_frame(int(dev_pid_raw), cuid, appid=appid, appkey=api_key)

    async def _read_first_frame(self, message_iter) -> bytes | None:
        buf = bytearray()
        while len(buf) < self._frame_bytes:
            try:
                message = await message_iter.__anext__()
            except StopAsyncIteration:
                return None
            if not isinstance(message, (bytes, bytearray)):
                continue
            buf.extend(message)
        frame = bytes(buf[:self._frame_bytes])
        del buf[:self._frame_bytes]
        return frame + bytes(buf)

    # ── one Baidu session per client ─────────────────────────────────────────

    async def _run_baidu_session(self, client_ws):
        """Stream audio from client_ws to Baidu, emit FIN_TEXT when done."""
        message_iter = client_ws.__aiter__()
        first_audio = await self._read_first_frame(message_iter)
        if first_audio is None:
            return False

        token = await self._get_access_token()
        baidu_url = _build_baidu_url(self.cfg.baidu_url, token)
        buf = bytearray()
        idle_timeout = float(os.getenv("BAIDU_AUDIO_IDLE_TIMEOUT", "2.0"))

        async with websockets.connect(baidu_url, open_timeout=8, close_timeout=1) as baidu_ws:
            await baidu_ws.send(await self._build_start_frame())

            # Sender: read from client, forward to Baidu
            async def sender():
                nonlocal buf
                last_audio_ts = time.monotonic()

                async def send_audio(audio: bytes):
                    nonlocal buf, last_audio_ts
                    if not audio:
                        return
                    self._feed_cry_detector(audio)
                    last_audio_ts = time.monotonic()
                    buf.extend(audio)
                    while len(buf) >= self._frame_bytes:
                        frame = bytes(buf[:self._frame_bytes])
                        del buf[:self._frame_bytes]
                        await baidu_ws.send(frame)

                await send_audio(first_audio)
                while True:
                    try:
                        message = await asyncio.wait_for(
                            message_iter.__anext__(),
                            timeout=0.5,
                        )
                    except asyncio.TimeoutError:
                        if time.monotonic() - last_audio_ts >= idle_timeout:
                            logger.info(
                                "baidu stream idle %.1fs waiting for mic audio; closing session",
                                idle_timeout,
                            )
                            break
                        continue
                    except StopAsyncIteration:
                        break
                    if isinstance(message, (bytes, bytearray)):
                        await send_audio(bytes(message))

                if buf:
                    await baidu_ws.send(bytes(buf))
                    buf.clear()
                await baidu_ws.send(json.dumps({"type": "FINISH"}, ensure_ascii=False))

            # Receiver: read Baidu responses, emit FIN_TEXT
            async def receiver():
                async for message in baidu_ws:
                    if isinstance(message, (bytes, bytearray)):
                        message = bytes(message).decode("utf-8", errors="replace")
                    try:
                        payload = json.loads(str(message))
                    except Exception:
                        continue
                    result_type = str(payload.get("type", "")).upper()
                    if result_type == "HEARTBEAT":
                        continue
                    err_no = int(payload.get("err_no", 0) or 0)
                    if err_no != 0:
                        if err_no == -3005:
                            logger.info("baidu no effective speech; restarting session")
                        else:
                            logger.warning("baidu err_no=%s err_msg=%s", err_no, payload.get("err_msg", ""))
                        await baidu_ws.close()
                        return
                    if result_type == "FIN_TEXT":
                        text = str(payload.get("result") or "").strip()
                        if text:
                            self._emit_text(text)

            sender_task = asyncio.create_task(sender())
            receiver_task = asyncio.create_task(receiver())
            done, pending = await asyncio.wait(
                {sender_task, receiver_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            results = []
            for task in done:
                if task.cancelled():
                    continue
                try:
                    results.append(task.result())
                except Exception as exc:
                    results.append(exc)
            results.extend(await asyncio.gather(*pending, return_exceptions=True))
            for result in results:
                if isinstance(result, ConnectionClosed):
                    logger.debug("baidu session closed: %s", result)
                elif isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    logger.warning("baidu session error: %s", result)
        return True

    # ── client handler ───────────────────────────────────────────────────────

    async def handle_client(self, ws):
        path = _safe_ws_path(ws)
        if self.cfg.path and path and path != self.cfg.path:
            await ws.close(1008, "invalid path")
            return

        peer = getattr(ws, "remote_address", None)
        logger.info("client connected: %s", peer)
        try:
            while True:
                if not await self._run_baidu_session(ws):
                    break
        except Exception as exc:
            logger.warning("client error: %s", exc)
        finally:
            logger.info("client disconnected: %s", peer)

    # ── server ───────────────────────────────────────────────────────────────

    async def run(self, stop_event=None):
        logger.info(
            "listen ws://%s:%s%s dev_pid=%s frame_ms=%s frame_bytes=%s",
            self.cfg.host, self.cfg.port, self.cfg.path,
            self.cfg.baidu_dev_pid, self.cfg.baidu_frame_ms, self._frame_bytes,
        )
        async with websockets.serve(
            self.handle_client,
            self.cfg.host,
            self.cfg.port,
            max_size=2 * 1024 * 1024,
        ):
            if stop_event is None:
                await asyncio.Future()
            else:
                while not stop_event.is_set():
                    await asyncio.sleep(0.2)
