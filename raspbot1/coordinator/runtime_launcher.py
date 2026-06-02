"""Top-level runtime launcher — car setup, then hands off to SystemCoordinator."""

import argparse
import os
import subprocess
import sys
import time
from typing import Optional

from pc_modules.auth_config import ensure_auth_token
from pc_modules.car_resolver import resolve_car
from pc_modules.discovery import DEFAULT_DISCOVERY_PORT
from pc_modules.logger_setup import setup_logger
from pc_modules.process_utils import install_exit_handlers, start_process
from pc_modules.protocol import append_auth_token_to_uri
from pc_modules.settings import DEFAULT_CAR_PORT

logger = setup_logger("raspbot.agent")


def wait_websocket(uri: str, timeout: float = 45.0, auth_token: str = "") -> bool:
    import asyncio
    import websockets

    probe_uri = append_auth_token_to_uri(uri, auth_token)

    async def _probe():
        async with websockets.connect(
            probe_uri, max_size=1024 * 1024,
            open_timeout=2, ping_timeout=2, close_timeout=1, proxy=None,
        ):
            return True

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            asyncio.run(_probe())
            return True
        except Exception:
            time.sleep(0.8)
    return False


def parse_args():
    p = argparse.ArgumentParser(description="Start car server + PC runtime")
    # -- Car --
    p.add_argument("--host", default=os.getenv("RASPBOT_CAR_IP", ""))
    p.add_argument("--port", type=int, default=int(os.getenv("RASPBOT_CAR_PORT", DEFAULT_CAR_PORT)))
    p.add_argument("--refresh-car-cache", action="store_true")
    p.add_argument("--no-car-cache", action="store_true",
                   default=os.getenv("RASPBOT_NO_CAR_CACHE", "").strip().lower() in {"1", "true", "yes", "on"})
    p.add_argument("--discover-timeout", type=float, default=10.0)
    p.add_argument("--discover-port", type=int, default=DEFAULT_DISCOVERY_PORT)
    # -- SSH --
    p.add_argument("--ssh-user", default=os.getenv("RASPBOT_SSH_USER", "pi"))
    p.add_argument("--ssh-password", default=os.getenv("RASPBOT_SSH_PASSWORD", None))
    p.add_argument("--auth-token", default=os.getenv("RASPBOT_AUTH_TOKEN", ""))
    p.add_argument("--trust-new-host-key", action="store_true",
                   default=os.getenv("RASPBOT_TRUST_NEW_HOST_KEY", "").strip().lower() in {"1", "true", "yes", "on"})
    p.add_argument("--skip-car-start", action="store_true")
    p.add_argument("--skip-car-sync", action="store_true")
    p.add_argument("--leave-car-running", action="store_true")
    p.add_argument("--remote-heartbeat-timeout", type=float,
                   default=float(os.getenv("RASPBOT_REMOTE_HEARTBEAT_TIMEOUT", "12")))
    p.add_argument("--disable-mic-stream", action="store_true")
    p.add_argument("--no-tail", action="store_true")
    # -- PC runtime --
    p.add_argument("--monitor", action="store_true", help="Start env/IMU monitor alongside.")
    p.add_argument("--no-monitor", action="store_true")
    p.add_argument("--no-pc", action="store_true", help="Do not start PC control client.")
    p.add_argument("--wait-port-timeout", type=float, default=50.0)
    # -- PC overrides (usually from env) --
    p.add_argument("--model", default=os.getenv("RASPBOT_MODEL", "best.pt"))
    p.add_argument("--yolo-device", default=os.getenv("RASPBOT_YOLO_DEVICE", "cuda"))
    p.add_argument("--yolo-use-cudnn", action="store_true")
    p.add_argument("--disable-asr", action="store_true")
    p.add_argument("--disable-webrtc-bridge", action="store_true",
                   default=os.getenv("RASPBOT_ENABLE_WEBRTC_BRIDGE", "1").strip().lower() in {"0", "false", "no", "off"})
    return p.parse_args()


def _check_hotspot(car_ip: str = "") -> bool:
    try:
        out = subprocess.run(
            "ipconfig", shell=True, capture_output=True, text=True, encoding="gbk", timeout=8
        ).stdout
    except Exception:
        return True
    car_prefix = ".".join(str(car_ip).split(".")[:3]) + "." if car_ip else ""
    for line in out.splitlines():
        if ("IPv4" in line or "IP" in line) and car_prefix and car_prefix in line:
            return True
        if "192.168.137" in line:
            return True
    return False


def _fill_pc_defaults(args):
    """Fill PC-side args from env when not already set by launcher parser."""
    defaults = {
        "tuning": os.getenv("RASPBOT_MOTION_TUNING",
                            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                         "motion_tuning.json")),
        "asr_host": os.getenv("ASR_HOST", "0.0.0.0"),
        "asr_port": int(os.getenv("ASR_PORT", "6006")),
        "asr_path": os.getenv("ASR_PATH", "/audio"),
        "asr_window_sec": float(os.getenv("ASR_WINDOW_SEC", "2.0")),
        "asr_step_sec": float(os.getenv("ASR_STEP_SEC", "1.0")),
        "asr_silence_rms": int(os.getenv("ASR_SILENCE_RMS", "220")),
        "baidu_appid": os.getenv("BAIDU_APPID", ""),
        "baidu_api_key": os.getenv("BAIDU_API_KEY", ""),
        "baidu_secret_key": os.getenv("BAIDU_SECRET_KEY", ""),
        "baidu_access_token": os.getenv("BAIDU_ACCESS_TOKEN", ""),
        "baidu_url": os.getenv("BAIDU_REALTIME_ASR_URL", "wss://vop.baidu.com/realtime_asr"),
        "baidu_dev_pid": int(os.getenv("BAIDU_DEV_PID", "15372")),
        "baidu_cuid": os.getenv("BAIDU_CUID", "raspbot-pc"),
        "baidu_lm_id": os.getenv("BAIDU_LM_ID", ""),
        "baidu_user": os.getenv("BAIDU_USER", ""),
        "baidu_frame_ms": int(os.getenv("BAIDU_FRAME_MS", "160")),
        "baidu_emit_partial": os.getenv("BAIDU_EMIT_PARTIAL", "").strip().lower() in {"1", "true", "yes", "on"},
        "webrtc_signaling_url": os.getenv("RASPBOT_WEBRTC_SIGNALING_URL", "ws://47.108.164.190:8765/pc_room"),
        "webrtc_stun_url": os.getenv("RASPBOT_STUN_URL", "stun:47.108.164.190:3478"),
        "webrtc_turn_url": os.getenv("RASPBOT_TURN_URL", "turn:47.108.164.190:3478"),
        "webrtc_turn_username": os.getenv("RASPBOT_TURN_USERNAME", "webrtc_user"),
        "webrtc_turn_credential": os.getenv("RASPBOT_TURN_CREDENTIAL", ""),
        "webrtc_env_interval": float(os.getenv("RASPBOT_WEBRTC_ENV_INTERVAL", "0.2")),
        "enable_webrtc_bridge": not bool(getattr(args, "disable_webrtc_bridge", False)),
        "no_discover": True,  # car already resolved
    }
    for k, v in defaults.items():
        if not hasattr(args, k):
            setattr(args, k, v)


def main():
    args = parse_args()
    auth_token = ensure_auth_token(args.auth_token)

    if not _check_hotspot(args.host):
        logger.error("未检测到热点/局域网 (192.168.137.x)。请先开启电脑热点。")
        raise SystemExit(1)

    from coordinator.system_coordinator import SystemCoordinator

    coordinator = SystemCoordinator(args, auth_token)
    mon_proc: Optional[subprocess.Popen] = None

    def cleanup():
        if mon_proc is not None and mon_proc.poll() is None:
            mon_proc.terminate()
        coordinator.shutdown()

    install_exit_handlers(cleanup)

    try:
        should_monitor = (args.monitor or args.no_pc) and not args.no_monitor
        if should_monitor:
            # Monitor needs the car endpoint before the coordinator starts,
            # so do a quick discovery-only pass.
            car = resolve_car(args)
            mon_cmd = [sys.executable, "-m", "pc_modules.env_monitor",
                        "--host", car.ip, "--port", str(car.port)]
            if auth_token:
                mon_cmd.extend(["--auth-token", auth_token])
            mon_proc = start_process("MON", mon_cmd)

        if not args.no_pc:
            from coordinator.system_coordinator import RuntimeEndpoint
            _fill_pc_defaults(args)
            coordinator.run()  # blocking — full lifecycle
        elif not should_monitor:
            logger.info("no local services requested; leaving car server running")
            args.leave_car_running = True
            return

    except KeyboardInterrupt:
        logger.info("stopping")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
