"""Local process startup and shutdown helpers."""

import atexit
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import List

from .discovery import CarDiscovery

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WINDOWS_CONSOLE_HANDLER = None


def _reader_thread(label: str, proc: subprocess.Popen):
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"[{label}] {line.rstrip()}", flush=True)


def start_process(label: str, command: List[str]) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    threading.Thread(target=_reader_thread, args=(label, proc), daemon=True).start()
    return proc


def build_pc_command(car: CarDiscovery, auth_token: str = "", pc_extra: str = "") -> List[str]:
    command = [sys.executable, "-m", "pc_modules.app", "--host", car.ip, "--port", str(car.port)]
    if auth_token:
        command.extend(["--auth-token", auth_token])
    if pc_extra.strip():
        command.extend(pc_extra.strip().split())
    return command


def install_exit_handlers(cleanup):
    atexit.register(cleanup)

    def _handle_signal(signum, _frame):
        cleanup()
        raise SystemExit(128 + int(signum))

    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle_signal)
        except (OSError, ValueError):
            pass

    if os.name != "nt":
        return

    try:
        import ctypes
    except Exception:
        return

    handler_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
    close_events = {2, 5, 6}
    interrupt_events = {0, 1}

    def _console_handler(ctrl_type):
        event = int(ctrl_type)
        if event in close_events:
            cleanup()
            return True
        if event in interrupt_events:
            cleanup()
            return False
        return False

    global _WINDOWS_CONSOLE_HANDLER
    _WINDOWS_CONSOLE_HANDLER = handler_type(_console_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_WINDOWS_CONSOLE_HANDLER, True)
