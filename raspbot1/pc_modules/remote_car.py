"""SSH/SFTP control for the remote Raspbot car runtime."""

import os
import shlex
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .logger_setup import setup_logger

logger = setup_logger("raspbot.remote-car")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REMOTE_SOURCE_DIR = PROJECT_ROOT.parent / "raspbot_remote"
SHARED_SOURCE_DIR = PROJECT_ROOT.parent / "raspbot_shared"
REMOTE_DIR = "/home/pi/raspbot"
REMOTE_SHARED_DIR = "/home/pi/raspbot/../raspbot_shared"
REMOTE_LOG = "/tmp/raspbot-car-server.log"
REMOTE_PID = "/tmp/raspbot-car-server.pid"
REMOTE_HEARTBEAT = "/tmp/raspbot-agent-heartbeat"
REMOTE_WATCHDOG_PID = "/tmp/raspbot-car-watchdog.pid"
REMOTE_WATCHDOG_LOG = "/tmp/raspbot-car-watchdog.log"
_SYNC_EXCLUDED_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_SYNC_EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".csv"}
_SYNC_EXCLUDED_NAMES = {".DS_Store", "Thumbs.db"}
_ALLOW_INSECURE_ENV = "RASPBOT_ALLOW_INSECURE"


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


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
                logger.info("trusted new car IP %s: host key matches existing known_hosts entry", self.host)
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
            args.extend(shlex.split(extra_args.strip()))
        arg_text = " ".join(shlex.quote(a) for a in args)
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
