"""Car-side runtime agent."""

import threading

from pc_modules.logger_setup import setup_logger

logger = setup_logger("raspbot.car-agent")


class CarAgent:
    """Owns car discovery, code sync, SSH start/stop, heartbeat, and log tail."""

    def __init__(self, args, auth_token: str):
        self.args = args
        self.auth_token = auth_token
        self.car = None
        self.remote = None
        self.tail_stop = threading.Event()
        self.heartbeat_stop = threading.Event()
        self.started_remote = False

    def start(self):
        from pc_modules.car_resolver import resolve_car
        from pc_modules.remote_car import (
            REMOTE_DIR, REMOTE_SHARED_DIR, REMOTE_SOURCE_DIR, SHARED_SOURCE_DIR, RemoteCar,
        )

        self.car = resolve_car(self.args)
        if self.args.skip_car_start:
            return self.car

        while True:
            heartbeat_timeout = 0.0 if self.args.leave_car_running else self.args.remote_heartbeat_timeout
            try:
                self.remote = RemoteCar(
                    self.car.ip,
                    user=self.args.ssh_user,
                    password=self.args.ssh_password,
                    trust_new_host_key=self.args.trust_new_host_key,
                )
                if not self.args.skip_car_sync:
                    uploaded = self.remote.sync_project(REMOTE_SOURCE_DIR)
                    logger.info("synced car code to %s (%s changed files)", REMOTE_DIR, uploaded)
                    shared_uploaded = self.remote.sync_project(SHARED_SOURCE_DIR, REMOTE_SHARED_DIR)
                    if shared_uploaded > 0:
                        logger.info("synced shared lib to %s (%s files)", REMOTE_SHARED_DIR, shared_uploaded)
                    if uploaded > 0 or shared_uploaded > 0:
                        result = self.remote.restart_discovery()
                        if result.exit_status == 0:
                            logger.info("remote %s", result.stdout)
                        else:
                            logger.warning("discovery restart failed: %s", result.stderr or result.stdout)
                result = self.remote.start_server(
                    disable_mic_stream=self.args.disable_mic_stream or self.args.disable_asr,
                    heartbeat_timeout=heartbeat_timeout,
                    auth_token=self.auth_token,
                )
                if result.exit_status != 0:
                    raise RuntimeError(result.stderr or result.stdout)
                logger.info("remote %s", result.stdout)
                self.started_remote = True
                break
            except Exception as exc:
                if self.remote is not None:
                    self.remote.close()
                    self.remote = None
                if not isinstance(self.car.raw, dict) or self.car.raw.get("source") != "cache":
                    raise
                logger.warning("cached car %s failed over SSH/startup: %s; refreshing discovery", self.car.ip, exc)
                self.args.refresh_car_cache = True
                self.car = resolve_car(self.args)

        if heartbeat_timeout > 0:
            threading.Thread(target=self._heartbeat_loop, args=(heartbeat_timeout,), daemon=True).start()
        if not self.args.no_tail:
            threading.Thread(target=self.remote.tail_log, args=(self.tail_stop,), daemon=True).start()
        return self.car

    def stop(self) -> None:
        self.tail_stop.set()
        self.heartbeat_stop.set()
        if self.remote is not None and self.started_remote and not self.args.leave_car_running:
            try:
                result = self.remote.stop_server()
                if result.exit_status == 0:
                    logger.info("remote %s", result.stdout)
                else:
                    logger.error("remote stop failed: %s", result.stderr or result.stdout)
            except Exception as exc:
                logger.error("remote stop error: %s", exc)
        if self.remote is not None:
            self.remote.close()

    @property
    def is_healthy(self) -> bool:
        """Car is healthy if SSH connected and remote server was started successfully."""
        return self.remote is not None and self.started_remote

    def _heartbeat_loop(self, heartbeat_timeout: float) -> None:
        interval = max(1.0, min(5.0, float(heartbeat_timeout) / 3.0))
        while not self.heartbeat_stop.wait(interval):
            try:
                self.remote.refresh_heartbeat()
            except Exception as exc:
                logger.warning("heartbeat refresh error: %s", exc)
