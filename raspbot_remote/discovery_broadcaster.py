#!/usr/bin/env python3
"""UDP discovery broadcaster for Raspbot car.

This tiny process is intentionally independent from car_server_modular.py so
PC/App can discover the car even when the main control server is not running.
"""

import argparse
import json
import os
import socket
import subprocess
import time
from typing import List


DEFAULT_NAME = "raspbot"
DEFAULT_ROLE = "car"
DEFAULT_SERVICE_PORT = 5001
DEFAULT_BROADCAST_PORT = 5002
DEFAULT_INTERVAL_SEC = 1.0


def get_ipv4_addresses() -> List[str]:
    ips = []
    try:
        out = subprocess.check_output(["hostname", "-I"], text=True, timeout=1.0)
        for token in out.split():
            if _is_usable_ipv4(token) and token not in ips:
                ips.append(token)
    except Exception:
        pass

    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if _is_usable_ipv4(ip):
                ips.append(ip)
        except Exception:
            pass
    return ips


def _is_usable_ipv4(value: str) -> bool:
    parts = value.strip().split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    if any(n < 0 or n > 255 for n in nums):
        return False
    return not value.startswith(("127.", "169.254."))


def is_tcp_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.2):
            return True
    except OSError:
        return False


def build_payload(args, seq: int) -> dict:
    ips = get_ipv4_addresses()
    return {
        "name": args.name,
        "role": args.role,
        "ip": ips[0] if ips else "",
        "ips": ips,
        "port": int(args.service_port),
        "server_running": is_tcp_listening(args.service_port),
        "hostname": socket.gethostname(),
        "seq": seq,
        "ts": int(time.time()),
    }


def run(args) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    seq = 0
    print(
        f"[DISCOVERY] broadcasting name={args.name} service={args.service_port} "
        f"udp={args.broadcast_port} interval={args.interval}s",
        flush=True,
    )
    while True:
        seq += 1
        payload = build_payload(args, seq)
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            sock.sendto(data, ("255.255.255.255", int(args.broadcast_port)))
        except OSError as exc:
            print(f"[DISCOVERY] send failed: {exc}", flush=True)
        if seq == 1 or seq % 30 == 0:
            print(f"[DISCOVERY] {payload}", flush=True)
        time.sleep(float(args.interval))


def parse_args():
    p = argparse.ArgumentParser(description="Raspbot UDP discovery broadcaster")
    p.add_argument("--name", default=os.getenv("RASPBOT_DISCOVERY_NAME", DEFAULT_NAME))
    p.add_argument("--role", default=os.getenv("RASPBOT_DISCOVERY_ROLE", DEFAULT_ROLE))
    p.add_argument("--service-port", type=int, default=int(os.getenv("RASPBOT_CAR_PORT", str(DEFAULT_SERVICE_PORT))))
    p.add_argument("--broadcast-port", type=int, default=int(os.getenv("RASPBOT_DISCOVERY_PORT", str(DEFAULT_BROADCAST_PORT))))
    p.add_argument("--interval", type=float, default=float(os.getenv("RASPBOT_DISCOVERY_INTERVAL", str(DEFAULT_INTERVAL_SEC))))
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
