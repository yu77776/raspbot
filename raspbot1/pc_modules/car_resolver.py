"""Resolve and cache the car websocket endpoint."""

import socket
import time
from pathlib import Path
from typing import Optional

from .auth_config import LOCAL_CONFIG_PATH, read_local_config, write_local_config
from .discovery import CarDiscovery, discover_car
from .logger_setup import setup_logger
from .settings import DEFAULT_CAR_HOST

logger = setup_logger("raspbot.car-resolver")

_CAR_CACHE_KEY = "car"


def load_cached_car(port: int, path: Path = LOCAL_CONFIG_PATH) -> Optional[CarDiscovery]:
    cfg = read_local_config(path)
    payload = cfg.get(_CAR_CACHE_KEY)
    if not isinstance(payload, dict):
        return None
    ip = str(payload.get("ip", "") or "").strip()
    if not ip:
        return None
    try:
        cached_port = int(payload.get("port", port) or port)
    except (TypeError, ValueError):
        cached_port = int(port)
    return CarDiscovery(
        name=str(payload.get("name", "raspbot") or "raspbot"),
        ip=ip,
        port=cached_port,
        server_running=False,
        hostname=str(payload.get("hostname", "") or ""),
        raw={"source": "cache"},
    )


def save_cached_car(car: CarDiscovery, path: Path = LOCAL_CONFIG_PATH) -> None:
    cfg = read_local_config(path)
    cfg[_CAR_CACHE_KEY] = {
        "name": car.name or "raspbot",
        "ip": car.ip,
        "port": int(car.port),
        "hostname": car.hostname or "",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    write_local_config(cfg, path)


def _tcp_probe(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout)):
            return True
    except OSError:
        return False


def _cached_car_reachable(car: CarDiscovery, *, skip_car_start: bool) -> bool:
    if _tcp_probe(car.ip, car.port, timeout=0.6):
        return True
    if skip_car_start:
        return False
    return _tcp_probe(car.ip, 22, timeout=0.8)


def resolve_car(args) -> CarDiscovery:
    if args.host:
        return CarDiscovery(
            name="raspbot",
            ip=args.host.strip(),
            port=int(args.port),
            server_running=False,
            hostname="",
            raw={"source": "explicit"},
        )

    if not args.no_car_cache and not args.refresh_car_cache:
        cached = load_cached_car(int(args.port))
        if cached:
            if _cached_car_reachable(cached, skip_car_start=args.skip_car_start):
                logger.info("using cached car ws://%s:%s", cached.ip, cached.port)
                return cached
            logger.warning("cached car ws://%s:%s not reachable; refreshing discovery", cached.ip, cached.port)

    logger.info("discovering car on udp://0.0.0.0:%s", args.discover_port)
    car = discover_car(timeout=args.discover_timeout, port=args.discover_port)
    if not car:
        fallback = (DEFAULT_CAR_HOST or "").strip()
        if not fallback:
            raise SystemExit("[AGENT] car discovery failed")
        logger.warning("discovery not found, fallback to default ws://%s:%s", fallback, args.port)
        return CarDiscovery(
            name="raspbot",
            ip=fallback,
            port=int(args.port),
            server_running=False,
            hostname="",
            raw={"source": "default"},
        )
    logger.info("found %s server_running=%s", car.uri, car.server_running)
    raw = dict(car.raw or {})
    raw["source"] = "discovery"
    car.raw = raw
    return car
