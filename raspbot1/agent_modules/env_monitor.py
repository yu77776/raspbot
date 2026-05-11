"""Lightweight websocket monitor for car environment and IMU packets."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import argparse
import asyncio
import json
import time

import websockets

from pc_modules import settings as cfg
from pc_modules.logger_setup import setup_logger
from pc_modules.protocol import append_auth_token_to_uri, resolve_auth_token
from .discovery import DEFAULT_DISCOVERY_PORT, discover_car

logger = setup_logger('raspbot.monitor')


def _fmt_float(value, default=0.0, digits=1):
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return f"{default:.{digits}f}"


def format_env_line(env: dict) -> str:
    imu = env.get("imu") or {}
    track = env.get("track", [])
    return (
        f"dist={_fmt_float(env.get('dist_cm'), 999.0)}cm "
        f"temp={_fmt_float(env.get('temp_c'), 0.0)}C "
        f"light={env.get('light_lux', env.get('light', ''))} "
        f"smoke={env.get('smoke', '')} "
        f"vol={env.get('volume', '')} "
        f"cry={env.get('crying', False)}:{env.get('cry_score', 0)} "
        f"alarm={env.get('alarm', '') or '-'} "
        f"yaw={_fmt_float(imu.get('yaw'), 0.0)} "
        f"rate={_fmt_float(imu.get('yaw_rate'), 0.0)} "
        f"imu_ok={bool(imu.get('healthy', False))} "
        f"track={track} "
        f"fps={env.get('fps', '')}"
    )


async def monitor_env(uri: str, print_interval: float = 0.5, reconnect_delay: float = 2.0):
    """Print MSG_ENV packets from the car websocket until interrupted."""
    last_print = 0.0
    while True:
        try:
            logger.info('connecting %s', uri)
            async with websockets.connect(
                uri,
                max_size=10 * 1024 * 1024,
                open_timeout=5,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=1,
                proxy=None,
            ) as ws:
                logger.info('connected')
                async for message in ws:
                    if not isinstance(message, (bytes, bytearray)) or not message:
                        continue
                    if message[0] != cfg.MSG_ENV:
                        continue
                    try:
                        env = json.loads(message[1:].decode("utf-8"))
                    except Exception as exc:
                        logger.warning('bad env packet: %s', exc)
                        continue
                    now = time.monotonic()
                    if now - last_print >= max(0.1, float(print_interval)):
                        last_print = now
                        logger.info('%s', format_env_line(env))
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            logger.warning('disconnected: %s; retry in %.1fs', exc, reconnect_delay)
            await asyncio.sleep(reconnect_delay)


def parse_args():
    parser = argparse.ArgumentParser(description="Monitor Raspbot env/IMU websocket packets")
    parser.add_argument("--host", default="", help="Car IP. If omitted, UDP discovery is used.")
    parser.add_argument("--port", type=int, default=cfg.DEFAULT_CAR_PORT)
    parser.add_argument("--uri", default="", help="Full websocket URI, overrides --host/--port.")
    parser.add_argument("--interval", type=float, default=0.5, help="Print interval in seconds.")
    parser.add_argument("--auth-token", default="", help="WebSocket auth token. Defaults to RASPBOT_AUTH_TOKEN.")
    parser.add_argument("--discover-timeout", type=float, default=5.0)
    parser.add_argument("--discover-port", type=int, default=DEFAULT_DISCOVERY_PORT)
    return parser.parse_args()


def main():
    args = parse_args()
    uri = args.uri.strip()
    host = args.host.strip()
    port = int(args.port)

    if not uri:
        if not host:
            car = discover_car(timeout=args.discover_timeout, port=args.discover_port)
            if not car:
                raise SystemExit("[MON] car discovery failed")
            host = car.ip
            port = car.port
        uri = f"ws://{host}:{port}"

    uri = append_auth_token_to_uri(uri, resolve_auth_token(args.auth_token))

    try:
        asyncio.run(monitor_env(uri, print_interval=args.interval))
    except KeyboardInterrupt:
        logger.info('stopped')


if __name__ == "__main__":
    main()
