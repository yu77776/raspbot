"""UDP discovery client for finding the Raspbot car."""

import argparse
import json
import socket
import time
from dataclasses import dataclass
from typing import Optional


DEFAULT_DISCOVERY_PORT = 5002


@dataclass
class CarDiscovery:
    name: str
    ip: str
    port: int
    server_running: bool = False
    hostname: str = ""
    raw: dict = None

    @property
    def uri(self) -> str:
        return f"ws://{self.ip}:{self.port}"


def discover_car(timeout: float = 3.0, port: int = DEFAULT_DISCOVERY_PORT, name: str = "raspbot") -> Optional[CarDiscovery]:
    """Listen for a car discovery broadcast and return the newest matching car."""
    deadline = time.monotonic() + float(timeout)
    latest = None

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", int(port)))
        sock.settimeout(0.25)

        while time.monotonic() < deadline:
            try:
                data, _addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                payload = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("role") != "car":
                continue
            if name and payload.get("name") != name:
                continue

            ip = str(payload.get("ip") or "").strip()
            if not ip:
                ips = payload.get("ips") or []
                ip = str(ips[0]).strip() if ips else ""
            if not ip:
                continue

            try:
                service_port = int(payload.get("port", 5001))
            except Exception:
                service_port = 5001

            latest = CarDiscovery(
                name=str(payload.get("name", name) or name),
                ip=ip,
                port=service_port,
                server_running=bool(payload.get("server_running", False)),
                hostname=str(payload.get("hostname", "") or ""),
                raw=payload,
            )
            if latest.server_running:
                return latest

    finally:
        sock.close()

    return latest


def main():
    p = argparse.ArgumentParser(description="Listen for Raspbot UDP discovery packets")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--port", type=int, default=DEFAULT_DISCOVERY_PORT)
    p.add_argument("--name", default="raspbot")
    args = p.parse_args()

    car = discover_car(timeout=args.timeout, port=args.port, name=args.name)
    if not car:
        print("not found")
        raise SystemExit(1)
    print(json.dumps(car.raw, ensure_ascii=False))
    print(car.uri)


if __name__ == "__main__":
    main()
