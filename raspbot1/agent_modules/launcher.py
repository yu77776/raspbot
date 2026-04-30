"""PC-side launcher for starting and monitoring the Raspbot system."""

import atexit
import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .discovery import DEFAULT_DISCOVERY_PORT, CarDiscovery, discover_car
from pc_modules.settings import DEFAULT_CAR_HOST, DEFAULT_CAR_PORT


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REMOTE_DIR = "/home/pi/raspbot"
REMOTE_LOG = "/tmp/raspbot-car-server.log"
REMOTE_PID = "/tmp/raspbot-car-server.pid"
REMOTE_HEARTBEAT = "/tmp/raspbot-agent-heartbeat"
REMOTE_WATCHDOG_PID = "/tmp/raspbot-car-watchdog.pid"
REMOTE_WATCHDOG_LOG = "/tmp/raspbot-car-watchdog.log"
_WINDOWS_CONSOLE_HANDLER = None


@dataclass
class RemoteResult:
    stdout: str
    stderr: str
    exit_status: int


class RemoteCar:
    def __init__(self, host: str, user: str = "pi", password: Optional[str] = None,
                 timeout: float = 12.0, trust_new_host_key: bool = False):
        self.host = host
        self.user = user
        self.password = password
        self.timeout = timeout
        self.trust_new_host_key = trust_new_host_key
        self._ssh = None

    @staticmethod
    def _known_hosts_path() -> Path:
        return Path.home() / ".ssh" / "known_hosts"

    def _fetch_remote_host_key(self, paramiko):
        sock = socket.create_connection((self.host, 22), timeout=self.timeout)
        transport = None
        try:
            transport = paramiko.Transport(sock)
            transport.start_client(timeout=self.timeout)
            return transport.get_remote_server_key()
        finally:
            if transport is not None:
                transport.close()
            else:
                sock.close()

    def _trust_host_if_key_is_known_alias(self, paramiko) -> bool:
        known_hosts = self._known_hosts_path()
        if not known_hosts.exists():
            return False

        host_keys = paramiko.HostKeys(str(known_hosts))
        remote_key = self._fetch_remote_host_key(paramiko)
        remote_key_type = remote_key.get_name()
        remote_key_blob = remote_key.asbytes()

        for _host, keys in host_keys.items():
            known_key = keys.get(remote_key_type)
            if known_key is not None and known_key.asbytes() == remote_key_blob:
                host_keys.add(self.host, remote_key_type, remote_key)
                host_keys.save(str(known_hosts))
                print(
                    f"[AGENT] trusted new car IP {self.host}: "
                    f"host key matches existing known_hosts entry",
                    flush=True,
                )
                return True
        return False

    def connect(self):
        if self._ssh is not None:
            return self._ssh
        try:
            import paramiko
        except ImportError as exc:
            raise RuntimeError("paramiko is required for SSH startup; install it or start the car manually") from exc

        client = paramiko.SSHClient()
        known_hosts = self._known_hosts_path()
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        known_hosts.touch(exist_ok=True)
        client.load_host_keys(str(known_hosts))
        if self.trust_new_host_key:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        auth_kwargs = {
            "look_for_keys": self.password is None,
            "allow_agent": self.password is None,
        }
        if self.password is not None:
            auth_kwargs["password"] = self.password
        try:
            client.connect(
                hostname=self.host,
                username=self.user,
                timeout=self.timeout,
                banner_timeout=self.timeout,
                auth_timeout=self.timeout,
                **auth_kwargs,
            )
        except paramiko.SSHException as exc:
            if self.trust_new_host_key or "not found in known_hosts" not in str(exc):
                raise
            if not self._trust_host_if_key_is_known_alias(paramiko):
                raise
            client = paramiko.SSHClient()
            client.load_host_keys(str(known_hosts))
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(
                hostname=self.host,
                username=self.user,
                timeout=self.timeout,
                banner_timeout=self.timeout,
                auth_timeout=self.timeout,
                **auth_kwargs,
            )
        self._ssh = client
        return client

    def close(self):
        if self._ssh is not None:
            self._ssh.close()
            self._ssh = None

    def exec(self, command: str, timeout: Optional[float] = None) -> RemoteResult:
        ssh = self.connect()
        stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout or self.timeout)
        del stdin
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return RemoteResult(stdout=out.strip(), stderr=err.strip(), exit_status=code)

    def start_server(
        self,
        *,
        asr_auto: bool = True,
        disable_mic_stream: bool = False,
        extra_args: str = "",
        heartbeat_timeout: float = 12.0,
    ) -> RemoteResult:
        args = []
        if disable_mic_stream:
            args.append("--disable-mic-stream")
        elif asr_auto:
            args.extend(["--asr-url", "auto"])
        if extra_args.strip():
            args.append(extra_args.strip())
        arg_text = " ".join(args)
        heartbeat_timeout_int = max(0, int(float(heartbeat_timeout or 0)))

        command = f"""
set -eu
cd {REMOTE_DIR}
if [ -f {REMOTE_WATCHDOG_PID} ]; then
  watchdog="$(cat {REMOTE_WATCHDOG_PID} 2>/dev/null || true)"
  if [ -n "$watchdog" ] && kill -0 "$watchdog" 2>/dev/null; then
    kill "$watchdog" 2>/dev/null || true
  fi
fi
if [ -f {REMOTE_PID} ]; then
  old="$(cat {REMOTE_PID} 2>/dev/null || true)"
  if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
    kill "$old" 2>/dev/null || true
    sleep 1
  fi
fi
for pid in $(pgrep -f 'car_server_modular.py' 2>/dev/null || true); do
  if [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then
    continue
  fi
  args_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  case "$args_line" in
    *python*car_server_modular.py*) kill "$pid" 2>/dev/null || true ;;
  esac
done
sleep 1
for pid in $(ps -eo pid=,args= | awk '/python/ && /car_server_modular.py/ {{print $1}}'); do
  if [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then
    continue
  fi
  kill -9 "$pid" 2>/dev/null || true
done
: > {REMOTE_LOG}
PYTHON_BIN=".venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi
setsid env PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 "$PYTHON_BIN" -u car_server_modular.py {arg_text} < /dev/null > {REMOTE_LOG} 2>&1 &
echo "$!" > {REMOTE_PID}
date +%s > {REMOTE_HEARTBEAT}
if [ {heartbeat_timeout_int} -gt 0 ]; then
  nohup sh -c '
pid_file="$1"
heartbeat_file="$2"
timeout_sec="$3"
while true; do
  car_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -z "$car_pid" ] || ! kill -0 "$car_pid" 2>/dev/null; then
    exit 0
  fi
  last="$(cat "$heartbeat_file" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  age=$((now - last))
  if [ "$age" -ge "$timeout_sec" ]; then
    echo "[WATCHDOG] launcher heartbeat stale age=${{age}}s timeout=${{timeout_sec}}s -> stop car server"
    kill "$car_pid" 2>/dev/null || true
    sleep 1
    kill -9 "$car_pid" 2>/dev/null || true
    rm -f "$pid_file" "$heartbeat_file"
    exit 0
  fi
  sleep 2
done
' sh {REMOTE_PID} {REMOTE_HEARTBEAT} {heartbeat_timeout_int} > {REMOTE_WATCHDOG_LOG} 2>&1 &
  echo "$!" > {REMOTE_WATCHDOG_PID}
fi
sleep 0.2
echo "started pid=$(cat {REMOTE_PID}) log={REMOTE_LOG} heartbeat_timeout={heartbeat_timeout_int}s"
"""
        return self.exec(command, timeout=8)

    def stop_server(self) -> RemoteResult:
        command = f"""
set +e
if [ -f {REMOTE_PID} ]; then
  old="$(cat {REMOTE_PID} 2>/dev/null || true)"
  if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
    kill "$old" 2>/dev/null || true
  fi
fi
sleep 1
for pid in $(pgrep -f 'car_server_modular.py' 2>/dev/null || true); do
  if [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then
    continue
  fi
  args_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  case "$args_line" in
    *python*car_server_modular.py*) kill "$pid" 2>/dev/null || true ;;
  esac
done
sleep 1
for pid in $(ps -eo pid=,args= | awk '/python/ && /car_server_modular.py/ {{print $1}}'); do
  if [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then
    continue
  fi
  kill -9 "$pid" 2>/dev/null || true
done
if [ -f {REMOTE_WATCHDOG_PID} ]; then
  watchdog="$(cat {REMOTE_WATCHDOG_PID} 2>/dev/null || true)"
  if [ -n "$watchdog" ] && kill -0 "$watchdog" 2>/dev/null; then
    kill "$watchdog" 2>/dev/null || true
  fi
fi
rm -f {REMOTE_PID} {REMOTE_HEARTBEAT} {REMOTE_WATCHDOG_PID}
echo "stopped car server"
"""
        return self.exec(command, timeout=8)

    def refresh_heartbeat(self) -> RemoteResult:
        return self.exec(f"date +%s > {REMOTE_HEARTBEAT}", timeout=4)

    def tail_log(self, stop_event: threading.Event, lines: int = 80):
        ssh = self.connect()
        command = f"tail -n {int(lines)} -F {REMOTE_LOG}"
        _stdin, stdout, stderr = ssh.exec_command(command, get_pty=True)
        del _stdin, stderr
        while not stop_event.is_set():
            line = stdout.readline()
            if not line:
                time.sleep(0.1)
                continue
            print(f"[CAR] {line.rstrip()}", flush=True)


def wait_tcp(host: str, port: int, timeout: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def wait_websocket(uri: str, timeout: float = 45.0) -> bool:
    import asyncio
    import websockets

    async def _probe():
        async with websockets.connect(
            uri,
            max_size=1024 * 1024,
            open_timeout=2,
            ping_timeout=2,
            close_timeout=1,
            proxy=None,
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


def resolve_car(args) -> CarDiscovery:
    if args.host:
        return CarDiscovery(name="raspbot", ip=args.host.strip(), port=int(args.port), server_running=False, hostname="")

    print(f"[AGENT] discovering car on udp://0.0.0.0:{args.discover_port}", flush=True)
    car = discover_car(timeout=args.discover_timeout, port=args.discover_port)
    if not car:
        fallback = (DEFAULT_CAR_HOST or "").strip()
        if not fallback:
            raise SystemExit("[AGENT] car discovery failed")
        print(f"[AGENT] discovery not found, fallback to default ws://{fallback}:{args.port}", flush=True)
        return CarDiscovery(name="raspbot", ip=fallback, port=int(args.port), server_running=False, hostname="")
    print(f"[AGENT] found {car.uri} server_running={car.server_running}", flush=True)
    return car


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


def parse_args():
    parser = argparse.ArgumentParser(description="Start car server, PC client, and env monitor")
    parser.add_argument("--host", default=os.getenv("RASPBOT_CAR_IP", ""), help="Car IP. If omitted, UDP discovery is used.")
    parser.add_argument("--port", type=int, default=int(os.getenv("RASPBOT_CAR_PORT", DEFAULT_CAR_PORT)))
    parser.add_argument("--discover-timeout", type=float, default=10.0)
    parser.add_argument("--discover-port", type=int, default=DEFAULT_DISCOVERY_PORT)
    parser.add_argument("--ssh-user", default=os.getenv("RASPBOT_SSH_USER", "pi"))
    parser.add_argument("--ssh-password", default=os.getenv("RASPBOT_SSH_PASSWORD", None))
    parser.add_argument(
        "--trust-new-host-key",
        action="store_true",
        default=os.getenv("RASPBOT_TRUST_NEW_HOST_KEY", "").strip().lower() in {"1", "true", "yes", "on"},
        help="Trust and store an unknown SSH host key. Default is to require a known_hosts entry.",
    )
    parser.add_argument("--skip-car-start", action="store_true", help="Do not SSH-start the car server.")
    parser.add_argument("--leave-car-running", action="store_true", help="Do not stop the remote car server when this launcher exits.")
    parser.add_argument(
        "--remote-heartbeat-timeout",
        type=float,
        default=float(os.getenv("RASPBOT_REMOTE_HEARTBEAT_TIMEOUT", "12")),
        help="Stop the car server if this launcher stops refreshing its remote heartbeat for N seconds. Use 0 to disable.",
    )
    parser.add_argument("--disable-mic-stream", action="store_true", help="Start car server without mic stream.")
    parser.add_argument("--no-tail", action="store_true", help="Do not tail remote car log.")
    parser.add_argument("--monitor", action="store_true", help="Start env/IMU monitor alongside the PC client.")
    parser.add_argument("--no-monitor", action="store_true", help="Do not start env/IMU monitor, even with --no-pc.")
    parser.add_argument("--no-pc", action="store_true", help="Do not start PC video/control client.")
    parser.add_argument("--wait-port-timeout", type=float, default=50.0)
    parser.add_argument("--pc-extra", default="", help="Extra arguments appended to pc_client_ws.py.")
    return parser.parse_args()


def main():
    args = parse_args()
    car = resolve_car(args)
    remote = None
    tail_stop = threading.Event()
    heartbeat_stop = threading.Event()
    processes: List[subprocess.Popen] = []
    cleanup_lock = threading.Lock()
    cleanup_done = False

    def cleanup():
        nonlocal cleanup_done
        with cleanup_lock:
            if cleanup_done:
                return
            cleanup_done = True
            tail_stop.set()
            heartbeat_stop.set()
            for proc in processes:
                if proc.poll() is None:
                    proc.terminate()
            for proc in processes:
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if remote is not None and not args.leave_car_running:
                try:
                    result = remote.stop_server()
                    if result.exit_status == 0:
                        print(f"[AGENT] remote {result.stdout}", flush=True)
                    else:
                        print(f"[AGENT] remote stop failed: {result.stderr or result.stdout}", flush=True)
                except Exception as exc:
                    print(f"[AGENT] remote stop error: {exc}", flush=True)
            if remote is not None:
                remote.close()

    install_exit_handlers(cleanup)

    try:
        if not args.skip_car_start:
            heartbeat_timeout = 0.0 if args.leave_car_running else args.remote_heartbeat_timeout
            remote = RemoteCar(
                car.ip,
                user=args.ssh_user,
                password=args.ssh_password,
                trust_new_host_key=args.trust_new_host_key,
            )
            result = remote.start_server(
                disable_mic_stream=args.disable_mic_stream,
                heartbeat_timeout=heartbeat_timeout,
            )
            if result.exit_status != 0:
                raise SystemExit(f"[AGENT] remote start failed: {result.stderr or result.stdout}")
            print(f"[AGENT] remote {result.stdout}", flush=True)
            if heartbeat_timeout > 0:
                def heartbeat_loop():
                    interval = max(1.0, min(5.0, float(heartbeat_timeout) / 3.0))
                    while not heartbeat_stop.wait(interval):
                        try:
                            remote.refresh_heartbeat()
                        except Exception as exc:
                            print(f"[AGENT] heartbeat refresh error: {exc}", flush=True)

                threading.Thread(target=heartbeat_loop, daemon=True).start()
            if not args.no_tail:
                threading.Thread(target=remote.tail_log, args=(tail_stop,), daemon=True).start()

        uri = f"ws://{car.ip}:{car.port}"

        should_monitor = (args.monitor or args.no_pc) and not args.no_monitor
        if should_monitor:
            processes.append(start_process("MON", [sys.executable, "-m", "agent_modules.env_monitor", "--host", car.ip, "--port", str(car.port)]))

        if not args.no_pc:
            pc_cmd = [sys.executable, "pc_client_ws.py", "--host", car.ip, "--port", str(car.port)]
            if args.pc_extra.strip():
                pc_cmd.extend(args.pc_extra.strip().split())
            processes.append(start_process("PC", pc_cmd))

        print(f"[AGENT] waiting for {uri}", flush=True)
        if not wait_tcp(car.ip, car.port, timeout=args.wait_port_timeout):
            raise SystemExit(f"[AGENT] car server port not ready: {car.ip}:{car.port}")
        if not wait_websocket(uri, timeout=max(5.0, args.wait_port_timeout)):
            raise SystemExit(f"[AGENT] car websocket handshake not ready: {uri}")
        print(f"[AGENT] car websocket is ready: {uri}", flush=True)

        if not processes:
            print("[AGENT] no local process requested; leaving car server running", flush=True)
            args.leave_car_running = True
            return

        while True:
            for proc in processes:
                code = proc.poll()
                if code is not None:
                    raise SystemExit(f"[AGENT] child process exited with code {code}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("[AGENT] stopping local processes", flush=True)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
