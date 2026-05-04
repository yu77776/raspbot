#!/usr/bin/env python3
"""
ASR websocket server for Raspbot microphone stream.

Compatible with car-side MicStream:
  - URL: ws://<pc_ip>:6006/audio
  - Payload: binary PCM16LE, 16kHz, mono

Default behavior:
  - Always consumes audio chunks to keep the link healthy.
  - Uses Baidu realtime ASR only.
"""

import argparse
import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import websockets

from .local_env import load_baidu_asr_config
from .logger_setup import setup_logger
from .protocol import _safe_ws_path

logger = setup_logger('raspbot.asr')

try:
    import audioop as _audioop
except Exception:
    _audioop = None


def _pcm16_rms(pcm16: bytes) -> float:
    """Compute RMS for PCM16LE. Falls back when audioop is unavailable."""
    if _audioop is not None:
        return float(_audioop.rms(pcm16, 2))
    if not pcm16:
        return 0.0
    import numpy as np

    audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio * audio)))


# ── YAMNet-based cry detection ──────────────────────────────────────────────
_yamnet_model = None
_yamnet_ok = None  # tri-state: None=unchecked, True=loaded, False=unavailable

# YAMNet AudioSet class indices for cry-related sounds
_YAMNET_CRY_CLASSES = (20, 27)  # 20=Baby cry/infant cry, 27=Crying/sobbing
_YAMNET_CRY_THRESHOLD = 0.25


def _init_yamnet():
    """Lazy-load YAMNet from TF Hub. Returns True on success."""
    global _yamnet_model, _yamnet_ok
    if _yamnet_model is not None:
        return True
    if _yamnet_ok is False:
        return False
    try:
        import tensorflow_hub as hub  # type: ignore
        _yamnet_model = hub.load('https://tfhub.dev/google/yamnet/1')
        _yamnet_ok = True
        logger.info('YAMNet loaded for cry detection (TF Hub)')
        return True
    except Exception as exc:
        logger.warning('YAMNet unavailable, using FFT fallback: %s', exc)
        _yamnet_ok = False
        return False


def _is_baby_cry_yamnet(pcm16: bytes, sample_rate: int = 16000,
                        threshold: float = _YAMNET_CRY_THRESHOLD) -> tuple:
    """Run YAMNet on PCM16 audio, return (is_cry, score in 0..1)."""
    if not _init_yamnet():
        return False, 0.0
    if not pcm16 or len(pcm16) < 640:
        return False, 0.0
    try:
        import numpy as np
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0

        # YAMNet was trained on 0.975s at 16 kHz (15600 samples).
        target = 15600
        if len(audio) > target:
            audio = audio[-target:]
        elif len(audio) < target:
            audio = np.pad(audio, (0, target - len(audio)))

        scores, _, _ = _yamnet_model(audio)
        # scores: (N_frames, 521) — average across time frames
        frame_mean = scores.numpy().mean(axis=0)
        score = float(max(frame_mean[i] for i in _YAMNET_CRY_CLASSES))
        return score >= threshold, round(score, 3)
    except Exception as exc:
        logger.warning('YAMNet inference error: %s', exc)
        return False, 0.0


def _is_baby_cry_spectrum(pcm16: bytes, sample_rate: int = 16000,
                          cry_low: float = 250.0, cry_high: float = 650.0,
                          ratio_threshold: float = 0.35) -> tuple:
    """FFT energy-ratio fallback when YAMNet is unavailable."""
    if not pcm16 or len(pcm16) < 640:
        return False, 0.0
    try:
        import numpy as np
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
        if audio.size < 320:
            return False, 0.0

        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), d=1.0 / sample_rate)

        valid = (freqs >= 50) & (freqs <= 4000)
        total_energy = np.sum(fft[valid] ** 2)
        if total_energy < 1e-6:
            return False, 0.0

        cry_band = (freqs >= cry_low) & (freqs <= cry_high)
        cry_energy = np.sum(fft[cry_band] ** 2)

        ratio = float(cry_energy / total_energy)
        return ratio >= ratio_threshold, round(ratio, 3)
    except Exception:
        return False, 0.0



def _load_local_baidu_config() -> dict:
    """Load local Baidu ASR secrets without hard-coding them in source."""
    return load_baidu_asr_config()



@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 6006
    path: str = "/audio"
    sample_rate: int = 16000
    window_sec: float = 2.0
    step_sec: float = 1.0
    silence_rms: int = 220
    baidu_appid: str = ""
    baidu_api_key: str = ""
    baidu_secret_key: str = ""
    baidu_access_token: str = ""
    baidu_url: str = "wss://vop.baidu.com/realtime_asr"
    baidu_dev_pid: int = 15372
    baidu_cuid: str = "raspbot-pc"
    baidu_lm_id: str = ""
    baidu_user: str = ""
    baidu_frame_ms: int = 160
    baidu_emit_partial: bool = False
    on_text: Optional[Callable[[str], None]] = None
    on_cry_state: Optional[Callable[[bool, float], None]] = None


class BaiduRealtimeEngine:
    """Baidu realtime ASR websocket engine.

    The local car->PC microphone websocket stays unchanged. This engine opens a
    provider websocket per car mic session, sends START/audio/FINISH frames, and
    emits only FIN_TEXT by default so robot commands use stable recognition.
    """

    name = "baidu-realtime"

    def __init__(self, cfg: ServerConfig):
        local_cfg = _load_local_baidu_config()
        self.appid = (
            cfg.baidu_appid or os.getenv("BAIDU_APPID", "") or local_cfg.get("appid", "")
        ).strip()
        self.api_key = (
            cfg.baidu_api_key or os.getenv("BAIDU_API_KEY", "") or local_cfg.get("api_key", "")
        ).strip()
        self.secret_key = (
            cfg.baidu_secret_key
            or os.getenv("BAIDU_SECRET_KEY", "")
            or local_cfg.get("secret_key", "")
        ).strip()
        self.access_token = (
            cfg.baidu_access_token
            or os.getenv("BAIDU_ACCESS_TOKEN", "")
            or local_cfg.get("access_token", "")
        ).strip()
        self.base_url = (
            cfg.baidu_url
            or os.getenv("BAIDU_REALTIME_ASR_URL", "")
            or local_cfg.get("url", "")
            or "wss://vop.baidu.com/realtime_asr"
        ).strip()
        self.dev_pid = int(
            cfg.baidu_dev_pid or os.getenv("BAIDU_DEV_PID", "") or local_cfg.get("dev_pid", 15372)
        )
        self.cuid = (
            cfg.baidu_cuid
            or os.getenv("BAIDU_CUID", "")
            or local_cfg.get("cuid", "")
            or "raspbot-pc"
        ).strip()
        self.lm_id = str(
            cfg.baidu_lm_id or os.getenv("BAIDU_LM_ID", "") or local_cfg.get("lm_id", "")
        ).strip()
        self.user = str(
            cfg.baidu_user or os.getenv("BAIDU_USER", "") or local_cfg.get("user", "")
        ).strip()
        self.frame_ms = int(
            cfg.baidu_frame_ms or os.getenv("BAIDU_FRAME_MS", "") or local_cfg.get("frame_ms", 160)
        )
        self.emit_partial = bool(cfg.baidu_emit_partial)
        if not self.access_token and (not self.api_key or not self.secret_key):
            raise RuntimeError(
                "BAIDU_ACCESS_TOKEN or both BAIDU_API_KEY and BAIDU_SECRET_KEY are required "
                "for Baidu realtime ASR"
            )
        if not self.api_key:
            self.api_key = os.getenv("BAIDU_API_KEY", "").strip()

    def get_access_token(self) -> str:
        if self.access_token:
            return self.access_token

        params = urlencode({
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        })
        url = f"https://aip.baidubce.com/oauth/2.0/token?{params}"
        req = Request(
            url,
            data=b"",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise RuntimeError(f"baidu token response missing access_token: {payload}")
        self.access_token = token
        return token

    async def build_url(self) -> str:
        token = await asyncio.to_thread(self.get_access_token)
        parts = urlsplit(self.base_url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params.setdefault("sn", str(uuid.uuid4()))
        params["token"] = token
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))

    def start_frame(self, sample_rate: int) -> str:
        data = {
            "appid": int(self.appid) if self.appid.isdigit() else self.appid,
            "appkey": self.api_key,
            "dev_pid": self.dev_pid,
            "cuid": self.cuid,
            "format": "pcm",
            "sample": int(sample_rate),
        }
        if not self.appid:
            data.pop("appid")
        if self.lm_id:
            data["lm_id"] = int(self.lm_id) if self.lm_id.isdigit() else self.lm_id
        if self.user or self.dev_pid == 15376:
            data["user"] = self.user or self.cuid
        return json.dumps({"type": "START", "data": data}, ensure_ascii=False)

    def frame_bytes(self, sample_rate: int) -> int:
        ms = max(20, min(200, int(self.frame_ms or 160)))
        return int(sample_rate * 2 * ms / 1000)

    def parse_text(self, message: str) -> tuple[str, bool]:
        payload = json.loads(message)
        result_type = str(payload.get("type", "")).upper()
        err_no = int(payload.get("err_no", 0) or 0)
        if result_type == "HEARTBEAT":
            return "", False
        if err_no != 0:
            logger.error('baidu error err_no=%s err_msg=%s', err_no, payload.get('err_msg', ''))
            return "", False
        text = str(payload.get("result") or "").strip()
        is_final = result_type == "FIN_TEXT"
        if not self.emit_partial and not is_final:
            return "", False
        return text, is_final


def _build_t2s_converter():
    """Build Traditional->Simplified converter with dependency fallback."""
    try:
        import opencc  # type: ignore

        cc = opencc.OpenCC("t2s")
        logger.info('text normalize: opencc t2s enabled')
        return cc.convert
    except Exception as exc:
        logger.warning('text normalize: builtin fallback (%s)', exc)
        table = str.maketrans({
            "進": "进",
            "後": "后",
            "轉": "转",
            "車": "车",
            "謝": "谢",
            "別": "别",
            "動": "动",
            "聲": "声",
            "開": "开",
            "關": "关",
            "線": "线",
            "們": "们",
            "這": "这",
            "個": "个",
            "會": "会",
            "嗎": "吗",
            "麼": "么",
            "說": "说",
            "讓": "让",
            "點": "点",
        })
        return lambda s: s.translate(table)


class AsrServer:
    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self.engine = BaiduRealtimeEngine(cfg)
        logger.info('engine=%s url=%s dev_pid=%s', self.engine.name, self.engine.base_url, self.engine.dev_pid)
        self.t2s = _build_t2s_converter()
        self.window_bytes = int(cfg.sample_rate * 2 * cfg.window_sec)
        self.step_bytes = max(320, int(cfg.sample_rate * 2 * cfg.step_sec))
        if self.step_bytes > self.window_bytes:
            self.step_bytes = self.window_bytes
        if _audioop is None:
            logger.warning('audioop unavailable, using numpy RMS fallback')

    def normalize_text(self, text: str) -> str:
        raw = (text or "").strip()
        if not raw:
            return ""
        try:
            return self.t2s(raw)
        except Exception:
            return raw

    def emit_text(self, text: str):
        text = self.normalize_text(text)
        if not text:
            return
        now = time.strftime("%H:%M:%S")
        logger.info('[%s] %s', now, text)
        if self.cfg.on_text is not None:
            try:
                self.cfg.on_text(text)
            except Exception as exc:
                logger.warning('on_text callback error: %s', exc)

    def emit_cry_if_needed(self, pcm16: bytes):
        if _yamnet_ok is None:
            _init_yamnet()
        if _yamnet_ok:
            is_cry, cry_ratio = _is_baby_cry_yamnet(pcm16, self.cfg.sample_rate)
        else:
            is_cry, cry_ratio = _is_baby_cry_spectrum(pcm16, self.cfg.sample_rate)
        if self.cfg.on_cry_state is not None:
            try:
                self.cfg.on_cry_state(is_cry, cry_ratio)
            except Exception as exc:
                logger.warning('on_cry_state callback error: %s', exc)
        if is_cry and self.cfg.on_text is not None:
            try:
                self.cfg.on_text(f"[CRY_DETECTED ratio={cry_ratio}]")
            except Exception as exc:
                logger.warning('on_text callback error: %s', exc)

    async def _run_baidu_stream(self, q: asyncio.Queue, stop: asyncio.Event):
        assert isinstance(self.engine, BaiduRealtimeEngine)

        url = await self.engine.build_url()
        pcm_buf = bytearray()
        frame_bytes = self.engine.frame_bytes(self.cfg.sample_rate)
        cry_buf = bytearray()
        last_text = ""

        async with websockets.connect(
            url,
            open_timeout=8,
            ping_interval=20,
            ping_timeout=10,
            max_size=None,
        ) as provider_ws:
            logger.info('baidu stream connected')
            await provider_ws.send(self.engine.start_frame(self.cfg.sample_rate))

            async def send_audio():
                nonlocal pcm_buf, cry_buf
                while not stop.is_set() or not q.empty():
                    try:
                        chunk = await asyncio.wait_for(q.get(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue
                    if not chunk:
                        continue
                    pcm_buf.extend(chunk)
                    cry_buf.extend(chunk)
                    while len(cry_buf) >= self.window_bytes:
                        pcm_window = bytes(cry_buf[: self.window_bytes])
                        del cry_buf[: self.step_bytes]
                        if _pcm16_rms(pcm_window) >= self.cfg.silence_rms:
                            self.emit_cry_if_needed(pcm_window)
                    while len(pcm_buf) >= frame_bytes:
                        frame = bytes(pcm_buf[:frame_bytes])
                        del pcm_buf[:frame_bytes]
                        await provider_ws.send(frame)

                if pcm_buf:
                    await provider_ws.send(bytes(pcm_buf))
                    pcm_buf.clear()
                try:
                    await provider_ws.send(json.dumps({"type": "FINISH"}, ensure_ascii=False))
                except Exception:
                    pass

            async def recv_text():
                nonlocal last_text
                async for message in provider_ws:
                    if isinstance(message, (bytes, bytearray)):
                        message = bytes(message).decode("utf-8", errors="replace")
                    try:
                        text, is_final = self.engine.parse_text(str(message))
                    except Exception as exc:
                        logger.warning('baidu parse error: %s', exc)
                        continue
                    if not text or text == last_text:
                        continue
                    last_text = text
                    if is_final or self.engine.emit_partial:
                        self.emit_text(text)

            send_task = asyncio.create_task(send_audio())
            recv_task = asyncio.create_task(recv_text())
            done, pending = await asyncio.wait(
                {send_task, recv_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in done:
                exc = task.exception()
                if exc is not None:
                    stop.set()
                    for pending_task in pending:
                        pending_task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    raise exc

            if send_task.done() and not recv_task.done():
                try:
                    await asyncio.wait_for(recv_task, timeout=3.0)
                except asyncio.TimeoutError:
                    recv_task.cancel()
                    await asyncio.gather(recv_task, return_exceptions=True)
            elif recv_task.done() and not send_task.done():
                stop.set()
                send_task.cancel()
                await asyncio.gather(send_task, return_exceptions=True)

    async def handle_client(self, ws):
        path = _safe_ws_path(ws)
        if self.cfg.path and path and path != self.cfg.path:
            logger.warning('reject path=%s expected=%s', path, self.cfg.path)
            await ws.close(code=1008, reason="invalid path")
            return

        peer = getattr(ws, "remote_address", None)
        logger.info('client connected: %s path=%s', peer, path or '/')

        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        stop = asyncio.Event()
        dropped = 0
        total_bytes = 0
        start_ts = time.time()

        async def recv_loop():
            nonlocal dropped, total_bytes
            try:
                async for message in ws:
                    if not isinstance(message, (bytes, bytearray)):
                        continue
                    chunk = bytes(message)
                    total_bytes += len(chunk)
                    try:
                        q.put_nowait(chunk)
                    except asyncio.QueueFull:
                        _ = q.get_nowait()
                        dropped += 1
                        q.put_nowait(chunk)
            finally:
                stop.set()

        async def asr_loop():
            try:
                await self._run_baidu_stream(q, stop)
            except Exception as exc:
                logger.warning('baidu stream error: %s', exc)

        try:
            await asyncio.gather(recv_loop(), asr_loop())
        except websockets.ConnectionClosed:
            pass
        finally:
            dur = max(0.001, time.time() - start_ts)
            kbps = (total_bytes * 8 / dur) / 1000
            logger.info('client disconnected: %s bytes=%s drop=%s avg_kbps=%.1f', peer, total_bytes, dropped, kbps)

    async def run(self, stop_event: Optional[threading.Event] = None):
        logger.info('listen ws://%s:%s%s sr=%s window=%ss step=%ss', self.cfg.host, self.cfg.port, self.cfg.path, self.cfg.sample_rate, self.cfg.window_sec, self.cfg.step_sec)
        async with websockets.serve(
            self.handle_client,
            self.cfg.host,
            self.cfg.port,
            max_size=None,
            ping_interval=20,
            ping_timeout=10,
        ):
            if stop_event is None:
                await asyncio.Future()
            else:
                while not stop_event.is_set():
                    await asyncio.sleep(0.2)


def parse_args():
    p = argparse.ArgumentParser(description="Raspbot ASR websocket server")
    p.add_argument("--host", default=os.getenv("ASR_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("ASR_PORT", "6006")))
    p.add_argument("--path", default=os.getenv("ASR_PATH", "/audio"))
    p.add_argument("--sample-rate", type=int, default=int(os.getenv("ASR_SAMPLE_RATE", "16000")))
    p.add_argument("--window-sec", type=float, default=float(os.getenv("ASR_WINDOW_SEC", "2.0")))
    p.add_argument("--step-sec", type=float, default=float(os.getenv("ASR_STEP_SEC", "1.0")))
    p.add_argument("--silence-rms", type=int, default=int(os.getenv("ASR_SILENCE_RMS", "220")))
    p.add_argument("--baidu-appid", default=os.getenv("BAIDU_APPID", ""))
    p.add_argument("--baidu-api-key", default=os.getenv("BAIDU_API_KEY", ""))
    p.add_argument("--baidu-secret-key", default=os.getenv("BAIDU_SECRET_KEY", ""))
    p.add_argument("--baidu-access-token", default=os.getenv("BAIDU_ACCESS_TOKEN", ""))
    p.add_argument("--baidu-url", default=os.getenv("BAIDU_REALTIME_ASR_URL", "wss://vop.baidu.com/realtime_asr"))
    p.add_argument("--baidu-dev-pid", type=int, default=int(os.getenv("BAIDU_DEV_PID", "15372")))
    p.add_argument("--baidu-cuid", default=os.getenv("BAIDU_CUID", "raspbot-pc"))
    p.add_argument("--baidu-lm-id", default=os.getenv("BAIDU_LM_ID", ""))
    p.add_argument("--baidu-user", default=os.getenv("BAIDU_USER", ""))
    p.add_argument("--baidu-frame-ms", type=int, default=int(os.getenv("BAIDU_FRAME_MS", "160")))
    p.add_argument(
        "--baidu-emit-partial",
        action="store_true",
        default=os.getenv("BAIDU_EMIT_PARTIAL", "").strip().lower() in {"1", "true", "yes", "on"},
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    cfg = ServerConfig(
        host=args.host,
        port=args.port,
        path=args.path,
        sample_rate=args.sample_rate,
        window_sec=args.window_sec,
        step_sec=args.step_sec,
        silence_rms=args.silence_rms,
        baidu_appid=args.baidu_appid,
        baidu_api_key=args.baidu_api_key,
        baidu_secret_key=args.baidu_secret_key,
        baidu_access_token=args.baidu_access_token,
        baidu_url=args.baidu_url,
        baidu_dev_pid=args.baidu_dev_pid,
        baidu_cuid=args.baidu_cuid,
        baidu_lm_id=args.baidu_lm_id,
        baidu_user=args.baidu_user,
        baidu_frame_ms=args.baidu_frame_ms,
        baidu_emit_partial=args.baidu_emit_partial,
    )
    asyncio.run(AsrServer(cfg).run())
