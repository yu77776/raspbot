"""PC-side launcher for starting and monitoring the Raspbot system."""

import atexit
import argparse
import json
import os
import signal
import shlex
import socket
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from .discovery import DEFAULT_DISCOVERY_PORT, CarDiscovery, discover_car
from pc_modules.logger_setup import setup_logger
from pc_modules.protocol import append_auth_token_to_uri
from pc_modules.settings import DEFAULT_CAR_HOST, DEFAULT_CAR_PORT

logger = setup_logger('raspbot.agent')


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_CONFIG_PATH = PROJECT_ROOT / "raspbot.local.json"
REMOTE_SOURCE_DIR = PROJECT_ROOT.parent / "raspbot_remote"
REMOTE_DIR = "/home/pi/raspbot"
REMOTE_LOG = "/tmp/raspbot-car-server.log"
REMOTE_PID = "/tmp/raspbot-car-server.pid"
REMOTE_HEARTBEAT = "/tmp/raspbot-agent-heartbeat"
REMOTE_WATCHDOG_PID = "/tmp/raspbot-car-watchdog.pid"
REMOTE_WATCHDOG_LOG = "/tmp/raspbot-car-watchdog.log"
_WINDOWS_CONSOLE_HANDLER = None
_SYNC_EXCLUDED_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_SYNC_EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".csv"}
_SYNC_EXCLUDED_NAMES = {".DS_Store", "Thumbs.db"}
_CAR_CACHE_KEY = "car"
_AUTH_TOKEN_ENV = "RASPBOT_AUTH_TOKEN"
_ALLOW_INSECURE_ENV = "RASPBOT_ALLOW_INSECURE"
ANDROID_LOCAL_PROPERTIES_PATH = PROJECT_ROOT.parent / "RaspbotApp" / "local.properties"


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _escape_properties_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")


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
                logger.info('trusted new car IP %s: host key matches existing known_hosts entry', self.host)
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

    def sync_project(self, local_dir: Path, remote_dir: str = REMOTE_DIR) -> int:
        """Upload changed car-side files before launching the remote server."""
        ssh = self.connect()
        local_dir = Path(local_dir)
        if not local_dir.is_dir():
            raise RuntimeError(f"remote source directory not found: {local_dir}")

        sftp = ssh.open_sftp()
        uploaded = 0
        try:
            _sftp_mkdirs(sftp, remote_dir)
            for path in _iter_remote_sync_files(local_dir):
                rel = path.relative_to(local_dir)
                remote_path = _remote_join(remote_dir, rel.parts)
                _sftp_mkdirs(sftp, _remote_parent(remote_path))
                stat = path.stat()
                if _remote_file_is_current(sftp, remote_path, stat.st_size, stat.st_mtime):
                    continue
                sftp.put(str(path), remote_path)
                try:
                    sftp.utime(remote_path, (int(stat.st_mtime), int(stat.st_mtime)))
                except Exception:
                    pass
                uploaded += 1
        finally:
            sftp.close()
        return uploaded

    def restart_discovery(self) -> RemoteResult:
        command = """
set +e
pkill -TERM -f '[d]iscovery_broadcaster.py'
sleep 3
if systemctl is-active --quiet raspbot-discovery.service 2>/dev/null; then
  echo "discovery service active"
else
  echo "discovery service not active"
fi
"""
        return self.exec(command, timeout=8)

    def start_server(
        self,
        *,
        asr_auto: bool = True,
        disable_mic_stream: bool = False,
        extra_args: str = "",
        heartbeat_timeout: float = 12.0,
        auth_token: str = "",
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
        env_parts = ["PYTHONUNBUFFERED=1", "PYTHONIOENCODING=utf-8"]
        if auth_token:
            env_parts.append(f"RASPBOT_AUTH_TOKEN={shlex.quote(auth_token)}")
        if _env_truthy(_ALLOW_INSECURE_ENV):
            env_parts.append("RASPBOT_ALLOW_INSECURE=1")
        env_text = " ".join(env_parts)

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
setsid env {env_text} "$PYTHON_BIN" -u car_server_modular.py {arg_text} < /dev/null > {REMOTE_LOG} 2>&1 &
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
    for _ in 1 2 3 4 5; do
      kill -0 "$car_pid" 2>/dev/null || break
      sleep 1
    done
    kill -0 "$car_pid" 2>/dev/null && kill -9 "$car_pid" 2>/dev/null || true
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
sleep 3
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


def wait_websocket(uri: str, timeout: float = 45.0, auth_token: str = "") -> bool:
    import asyncio
    import websockets

    probe_uri = append_auth_token_to_uri(uri, auth_token)

    async def _probe():
        async with websockets.connect(
            probe_uri,
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


def _remote_join(root: str, parts: Iterable[str]) -> str:
    out = root.rstrip("/")
    for part in parts:
        clean = str(part).replace("\\", "/").strip("/")
        if clean:
            out += "/" + clean
    return out or "/"


def _remote_parent(path: str) -> str:
    parent = path.rsplit("/", 1)[0]
    return parent if parent else "/"


def _should_sync_remote_file(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    if any(part in _SYNC_EXCLUDED_DIRS for part in rel_parts[:-1]):
        return False
    name = path.name
    if name in _SYNC_EXCLUDED_NAMES:
        return False
    if name.endswith(".local.json") or name.startswith(".env"):
        return False
    if path.suffix.lower() in _SYNC_EXCLUDED_SUFFIXES:
        return False
    return True


def _iter_remote_sync_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and _should_sync_remote_file(path, root):
            yield path


def _sftp_mkdirs(sftp, remote_dir: str) -> None:
    remote_dir = remote_dir.replace("\\", "/").rstrip("/") or "/"
    if remote_dir == "/":
        return
    cur = ""
    for part in remote_dir.strip("/").split("/"):
        cur += "/" + part
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)
        except OSError as exc:
            if getattr(exc, "errno", None) == 2:
                sftp.mkdir(cur)
            else:
                raise


def _remote_file_is_current(sftp, remote_path: str, size: int, mtime: float) -> bool:
    try:
        st = sftp.stat(remote_path)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    remote_size = int(getattr(st, "st_size", -1))
    remote_mtime = int(getattr(st, "st_mtime", 0))
    return remote_size == int(size) and abs(remote_mtime - int(mtime)) <= 1


def _read_local_config(path: Path = LOCAL_CONFIG_PATH) -> dict:
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning('cannot read local config %s: %s', path, exc)
        return {}


def _write_local_config(config: dict, path: Path = LOCAL_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def _set_local_env_value(key: str, value: str, path: Path = LOCAL_CONFIG_PATH) -> bool:
    cfg = _read_local_config(path)
    env = cfg.get("env")
    if not isinstance(env, dict):
        env = {}
        cfg["env"] = env
    if str(env.get(key, "") or "").strip() == value:
        return False
    env[key] = value
    _write_local_config(cfg, path)
    return True


def _sync_android_auth_token(token: str, path: Path = ANDROID_LOCAL_PROPERTIES_PATH) -> bool:
    token = str(token or "").strip()
    if not token:
        return False
    line_value = f"{_AUTH_TOKEN_ENV}={_escape_properties_value(token)}"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    lines = text.splitlines(keepends=True)
    updated = False
    found = False
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped and stripped[0] not in "#!":
            key_part = stripped.split("=", 1)[0].split(":", 1)[0].strip()
            if key_part == _AUTH_TOKEN_ENV:
                found = True
                newline = "\r\n" if line.endswith("\r\n") else "\n"
                replacement = line_value + newline
                out.append(replacement)
                updated = updated or replacement != line
                continue
        out.append(line)
    if not found:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += "\n"
            updated = True
        out.append(line_value + "\n")
        updated = True
    if updated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(out), encoding="utf-8")
    return updated


def _ensure_auth_token(
    requested_token: str = "",
    *,
    config_path: Path = LOCAL_CONFIG_PATH,
    android_properties_path: Path = ANDROID_LOCAL_PROPERTIES_PATH,
) -> str:
    auth_token = str(requested_token or os.getenv(_AUTH_TOKEN_ENV, "")).strip()
    if not auth_token and not _env_truthy(_ALLOW_INSECURE_ENV):
        cfg = _read_local_config(config_path)
        env = cfg.get("env", {})
        if isinstance(env, dict):
            auth_token = str(env.get(_AUTH_TOKEN_ENV, "") or "").strip()
    if not auth_token:
        if _env_truthy(_ALLOW_INSECURE_ENV):
            logger.warning(
                '%s is not set; continuing because %s=1 is enabled for this environment',
                _AUTH_TOKEN_ENV,
                _ALLOW_INSECURE_ENV,
            )
            return ""
        auth_token = secrets.token_urlsafe(32)
        logger.info('generated local %s for authenticated car/app websocket startup', _AUTH_TOKEN_ENV)
    changed_config = _set_local_env_value(_AUTH_TOKEN_ENV, auth_token, path=config_path)
    changed_app = _sync_android_auth_token(auth_token, path=android_properties_path)
    os.environ[_AUTH_TOKEN_ENV] = auth_token
    if changed_config:
        logger.info('saved %s to %s', _AUTH_TOKEN_ENV, config_path.name)
    if changed_app:
        logger.info('synced %s to Android local.properties', _AUTH_TOKEN_ENV)
    return auth_token


def _load_cached_car(port: int, path: Path = LOCAL_CONFIG_PATH) -> Optional[CarDiscovery]:
    cfg = _read_local_config(path)
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


def _save_cached_car(car: CarDiscovery, path: Path = LOCAL_CONFIG_PATH) -> None:
    cfg = _read_local_config(path)
    cfg[_CAR_CACHE_KEY] = {
        "name": car.name or "raspbot",
        "ip": car.ip,
        "port": int(car.port),
        "hostname": car.hostname or "",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _write_local_config(cfg, path)


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
        return CarDiscovery(name="raspbot", ip=args.host.strip(), port=int(args.port), server_running=False, hostname="", raw={"source": "explicit"})

    if not args.no_car_cache and not args.refresh_car_cache:
        cached = _load_cached_car(int(args.port))
        if cached:
            if _cached_car_reachable(cached, skip_car_start=args.skip_car_start):
                logger.info('using cached car ws://%s:%s', cached.ip, cached.port)
                return cached
            logger.warning('cached car ws://%s:%s not reachable; refreshing discovery', cached.ip, cached.port)

    logger.info('discovering car on udp://0.0.0.0:%s', args.discover_port)
    car = discover_car(timeout=args.discover_timeout, port=args.discover_port)
    if not car:
        fallback = (DEFAULT_CAR_HOST or "").strip()
        if not fallback:
            raise SystemExit("[AGENT] car discovery failed")
        logger.warning('discovery not found, fallback to default ws://%s:%s', fallback, args.port)
        return CarDiscovery(name="raspbot", ip=fallback, port=int(args.port), server_running=False, hostname="", raw={"source": "default"})
    logger.info('found %s server_running=%s', car.uri, car.server_running)
    raw = dict(car.raw or {})
    raw["source"] = "discovery"
    car.raw = raw
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
    parser.add_argument(
        "--refresh-car-cache",
        action="store_true",
        help="Ignore the cached car IP once and refresh it through UDP discovery.",
    )
    parser.add_argument(
        "--no-car-cache",
        action="store_true",
        default=os.getenv("RASPBOT_NO_CAR_CACHE", "").strip().lower() in {"1", "true", "yes", "on"},
        help="Disable cached car IP lookup and saving.",
    )
    parser.add_argument("--discover-timeout", type=float, default=10.0)
    parser.add_argument("--discover-port", type=int, default=DEFAULT_DISCOVERY_PORT)
    parser.add_argument("--ssh-user", default=os.getenv("RASPBOT_SSH_USER", "pi"))
    parser.add_argument("--ssh-password", default=os.getenv("RASPBOT_SSH_PASSWORD", None))
    parser.add_argument("--auth-token", default=os.getenv("RASPBOT_AUTH_TOKEN", ""))
    parser.add_argument(
        "--trust-new-host-key",
        action="store_true",
        default=os.getenv("RASPBOT_TRUST_NEW_HOST_KEY", "").strip().lower() in {"1", "true", "yes", "on"},
        help="Trust and store an unknown SSH host key. Default is to require a known_hosts entry.",
    )
    parser.add_argument("--skip-car-start", action="store_true", help="Do not SSH-start the car server.")
    parser.add_argument("--skip-car-sync", action="store_true", help="Do not upload local raspbot_remote files before SSH-starting the car server.")
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
    auth_token = _ensure_auth_token(args.auth_token)
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
                        logger.info('remote %s', result.stdout)
                    else:
                        logger.error('remote stop failed: %s', result.stderr or result.stdout)
                except Exception as exc:
                    logger.error('remote stop error: %s', exc)
            if remote is not None:
                remote.close()

    install_exit_handlers(cleanup)

    try:
        if not args.skip_car_start:
            while True:
                heartbeat_timeout = 0.0 if args.leave_car_running else args.remote_heartbeat_timeout
                try:
                    remote = RemoteCar(
                        car.ip,
                        user=args.ssh_user,
                        password=args.ssh_password,
                        trust_new_host_key=args.trust_new_host_key,
                    )
                    if not args.skip_car_sync:
                        uploaded = remote.sync_project(REMOTE_SOURCE_DIR)
                        logger.info('synced car code to %s (%s changed files)', REMOTE_DIR, uploaded)
                        if uploaded > 0:
                            result = remote.restart_discovery()
                            if result.exit_status == 0:
                                logger.info('remote %s', result.stdout)
                            else:
                                logger.warning('discovery restart failed: %s', result.stderr or result.stdout)
                    result = remote.start_server(
                        disable_mic_stream=args.disable_mic_stream,
                        heartbeat_timeout=heartbeat_timeout,
                        auth_token=auth_token,
                    )
                    if result.exit_status != 0:
                        raise RuntimeError(result.stderr or result.stdout)
                    logger.info('remote %s', result.stdout)
                    break
                except Exception as exc:
                    if remote is not None:
                        remote.close()
                        remote = None
                    if not isinstance(car.raw, dict) or car.raw.get("source") != "cache":
                        raise
                    logger.warning('cached car %s failed over SSH/startup: %s; refreshing discovery', car.ip, exc)
                    args.refresh_car_cache = True
                    car = resolve_car(args)
            if heartbeat_timeout > 0:
                def heartbeat_loop():
                    interval = max(1.0, min(5.0, float(heartbeat_timeout) / 3.0))
                    while not heartbeat_stop.wait(interval):
                        try:
                            remote.refresh_heartbeat()
                        except Exception as exc:
                            logger.warning('heartbeat refresh error: %s', exc)

                threading.Thread(target=heartbeat_loop, daemon=True).start()
            if not args.no_tail:
                threading.Thread(target=remote.tail_log, args=(tail_stop,), daemon=True).start()

        uri = f"ws://{car.ip}:{car.port}"

        should_monitor = (args.monitor or args.no_pc) and not args.no_monitor
        if should_monitor:
            mon_cmd = [sys.executable, "-m", "agent_modules.env_monitor", "--host", car.ip, "--port", str(car.port)]
            if auth_token:
                mon_cmd.extend(["--auth-token", auth_token])
            processes.append(start_process("MON", mon_cmd))

        if not args.no_pc:
            pc_cmd = [sys.executable, "pc_client_ws.py", "--host", car.ip, "--port", str(car.port)]
            if auth_token:
                pc_cmd.extend(["--auth-token", auth_token])
            if args.pc_extra.strip():
                pc_cmd.extend(args.pc_extra.strip().split())
            processes.append(start_process("PC", pc_cmd))

        logger.info('waiting for %s', uri)
        if not wait_websocket(uri, timeout=max(5.0, args.wait_port_timeout), auth_token=auth_token):
            raise SystemExit(f"[AGENT] car websocket handshake not ready: {uri}")
        logger.info('car websocket is ready: %s', uri)
        if not args.no_car_cache:
            try:
                _save_cached_car(car)
                logger.info('cached car endpoint: ws://%s:%s', car.ip, car.port)
            except Exception as exc:
                logger.warning('failed to cache car endpoint: %s', exc)

        if not processes:
            logger.info('no local process requested; leaving car server running')
            args.leave_car_running = True
            return

        while True:
            for proc in processes:
                code = proc.poll()
                if code is not None:
                    raise SystemExit(f"[AGENT] child process exited with code {code}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info('stopping local processes')
    finally:
        cleanup()


if __name__ == "__main__":
    main()
