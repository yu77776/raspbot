"""System coordinator — unified lifecycle, health monitoring, graceful shutdown.

Orchestrates the full runtime: Car → PC → App, with dependency ordering
and background health checks.  This is the single place that understands
how the three agents depend on each other.
"""

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from pc_agents.app_agent import AppAgent
from pc_agents.car_agent import CarAgent
from pc_agents.pc_agent import PcAgent
from pc_modules.app_gateway import TrackingModeStore
from pc_modules.logger_setup import setup_logger
from pc_modules.protocol import append_auth_token_to_uri, resolve_auth_token
from pc_modules.settings import DEFAULT_CAR_HOST, DEFAULT_CAR_PORT
from pc_modules.voice_cry_bridge import CryStateStore

logger = setup_logger("raspbot.coordinator")


@dataclass
class RuntimeEndpoint:
    host: str
    port: int
    auth_token: str = ""

    @property
    def uri(self) -> str:
        return f"ws://{self.host}:{self.port}"

    @property
    def auth_uri(self) -> str:
        return append_auth_token_to_uri(self.uri, self.auth_token)


@dataclass
class SharedRuntimeState:
    cry_state: CryStateStore
    tracking_mode_store: TrackingModeStore


class AgentStatus(Enum):
    IDLE = auto()
    STARTING = auto()
    RUNNING = auto()
    DEGRADED = auto()
    STOPPING = auto()
    STOPPED = auto()
    FAILED = auto()


class SystemCoordinator:
    """Orchestrate the three runtime agents with proper lifecycle ordering.

    Dependency chain:
      CarAgent  →  discovers car, syncs code, starts remote server
      PcAgent   →  needs car endpoint → YOLO + PID + ASR
      AppAgent  →  needs PC client → WebRTC bridge

    The coordinator enforces Car-ready before PC-start, and PC-ready
    before App-start.  A background health monitor tracks each agent
    and logs degradation.

    Usage:
      # Full lifecycle (car discovery + start):
      coordinator = SystemCoordinator(args, auth_token)
      coordinator.run()

      # Car already running, just start PC+App:
      coordinator = SystemCoordinator(args, auth_token)
      coordinator.run_with_endpoint(endpoint)
    """

    HEALTH_CHECK_INTERVAL_SEC = 3.0
    HEALTH_LOG_INTERVAL_SEC = 30.0

    def __init__(self, args, auth_token: str):
        self.args = args
        self.auth_token = auth_token

        # Agents — created lazily as dependencies become ready
        self.car_agent: Optional[CarAgent] = None
        self.pc_agent: Optional[PcAgent] = None
        self.app_agent: Optional[AppAgent] = None

        # Shared state — created when PC agent is wired
        self.shared_state: Optional[SharedRuntimeState] = None

        # Health tracking
        self._status: dict[str, AgentStatus] = {
            "car": AgentStatus.IDLE,
            "pc": AgentStatus.IDLE,
            "app": AgentStatus.IDLE,
        }
        self._stop_event = threading.Event()
        self._health_thread: Optional[threading.Thread] = None
        self._last_health_log = 0.0

    # ── Status API ────────────────────────────────────────────────

    @property
    def status(self) -> dict[str, str]:
        return {k: v.name for k, v in self._status.items()}

    @property
    def all_healthy(self) -> bool:
        return all(
            s in (AgentStatus.RUNNING, AgentStatus.IDLE)
            for s in self._status.values()
        )

    # ── Full lifecycle (car discovery + start) ────────────────────

    def run(self):
        """Full orchestration: discover car → start server → PC → App."""
        self._phase("car", AgentStatus.STARTING)
        self.car_agent = CarAgent(self.args, self.auth_token)

        try:
            car = self.car_agent.start()
        except Exception:
            self._phase("car", AgentStatus.FAILED)
            raise

        self._phase("car", AgentStatus.RUNNING)
        endpoint = RuntimeEndpoint(host=car.ip, port=car.port, auth_token=self.auth_token)
        logger.info("car ready at %s", endpoint.auth_uri)

        # Cache the endpoint for future runs
        try:
            from pc_modules.car_resolver import save_cached_car
            save_cached_car(car)
            logger.info("cached car endpoint: %s", endpoint.uri)
        except Exception as exc:
            logger.warning("failed to cache car endpoint: %s", exc)

        self._run_pc_app_chain(endpoint)

    # ── PC+App chain (car already running) ────────────────────────

    def run_with_endpoint(self, endpoint: RuntimeEndpoint):
        """Start PC + App agents against an already-running car."""
        self._phase("car", AgentStatus.RUNNING)  # assume car is up
        self._run_pc_app_chain(endpoint)

    def _run_pc_app_chain(self, endpoint: RuntimeEndpoint):
        """Internal: wire PC → App and run the blocking control loop."""
        # --- Shared state ---
        self.shared_state = SharedRuntimeState(
            cry_state=CryStateStore(),
            tracking_mode_store=TrackingModeStore(enabled=True),
        )

        # --- PC Agent ---
        self._phase("pc", AgentStatus.STARTING)
        self.pc_agent = PcAgent(self.args, endpoint, endpoint.auth_token, self.shared_state)
        self.pc_agent.start()
        self._phase("pc", AgentStatus.RUNNING)
        logger.info("pc agent running — YOLO=%s ASR=%s",
                     self.args.model,
                     "disabled" if self.args.disable_asr else f"ws://{self.args.asr_host}:{self.args.asr_port}")

        # --- App Agent ---
        self._phase("app", AgentStatus.STARTING)
        self.app_agent = AppAgent(
            self.args, endpoint, endpoint.auth_token,
            self.shared_state, self.pc_agent.client,
        )
        self.app_agent.start()
        self._phase("app", AgentStatus.RUNNING)
        logger.info("app agent running — WebRTC bridge %s",
                     "disabled" if not self.args.enable_webrtc_bridge else self.args.webrtc_signaling_url)

        # --- Health monitor ---
        self._health_thread = threading.Thread(target=self._health_loop, daemon=True, name="coord-health")
        self._health_thread.start()

        # --- Block on PC control loop ---
        try:
            logger.info("all agents running — entering control loop")
            self.pc_agent.run()  # blocking
        except KeyboardInterrupt:
            logger.info("keyboard interrupt — shutting down")
        except Exception as exc:
            logger.error("pc agent crashed: %s", exc)
        finally:
            self._stop_event.set()
            self.shutdown()

    # ── Health monitoring ─────────────────────────────────────────

    def _health_loop(self):
        """Background: check each agent periodically, log degradation."""
        while not self._stop_event.wait(self.HEALTH_CHECK_INTERVAL_SEC):
            self._check_health()
            self._maybe_log_status()

    def _check_health(self):
        self._check_agent_health("car", self.car_agent, "heartbeat may be lost")
        self._check_agent_health("pc", self.pc_agent, "control client or ASR service may have failed")
        self._check_agent_health("app", self.app_agent, "WebRTC bridge may have failed")

    def _check_agent_health(self, name, agent, degrade_hint):
        """Transition RUNNING <-> DEGRADED based on current health.

        Recovery is allowed so transient startup/warmup blips (e.g. ASR model
        load, control-client reconnect) do not lock the agent into DEGRADED
        forever once the underlying issue clears.
        """
        if agent is None:
            return
        prev = self._status[name]
        healthy = agent.is_healthy
        if prev == AgentStatus.RUNNING and not healthy:
            self._status[name] = AgentStatus.DEGRADED
            logger.warning("%s agent DEGRADED — %s", name, degrade_hint)
        elif prev == AgentStatus.DEGRADED and healthy:
            self._status[name] = AgentStatus.RUNNING
            logger.info("%s agent recovered — back to RUNNING", name)

    def _maybe_log_status(self):
        now = time.monotonic()
        if now - self._last_health_log < self.HEALTH_LOG_INTERVAL_SEC:
            return
        self._last_health_log = now
        status_line = " | ".join(f"{name}={status.name}" for name, status in self._status.items())
        if self.all_healthy:
            logger.info("health: %s", status_line)
        else:
            logger.warning("health: %s", status_line)

    # ── Shutdown ──────────────────────────────────────────────────

    def shutdown(self):
        """Graceful stop: App → PC → Car (reverse dependency order)."""
        logger.info("coordinator shutdown — stopping agents in reverse order")

        # App first (depends on PC)
        if self.app_agent is not None:
            self._phase("app", AgentStatus.STOPPING)
            try:
                self.app_agent.stop()
                self._phase("app", AgentStatus.STOPPED)
            except Exception as exc:
                self._phase("app", AgentStatus.FAILED)
                logger.error("app agent stop error: %s", exc)

        # PC next (depends on Car)
        if self.pc_agent is not None:
            self._phase("pc", AgentStatus.STOPPING)
            try:
                self.pc_agent.stop()
                self._phase("pc", AgentStatus.STOPPED)
            except Exception as exc:
                self._phase("pc", AgentStatus.FAILED)
                logger.error("pc agent stop error: %s", exc)

        # Car last
        if self.car_agent is not None:
            self._phase("car", AgentStatus.STOPPING)
            try:
                self.car_agent.stop()
                self._phase("car", AgentStatus.STOPPED)
            except Exception as exc:
                self._phase("car", AgentStatus.FAILED)
                logger.error("car agent stop error: %s", exc)

        logger.info("all agents stopped")

    def _phase(self, agent: str, status: AgentStatus):
        self._status[agent] = status


# ── Standalone endpoint resolution (used by app.py when no coordinator) ──

def resolve_endpoint(args) -> RuntimeEndpoint:
    """Resolve car endpoint from args or UDP discovery.  Used when the
    full coordinator lifecycle isn't needed (e.g. app.py standalone)."""
    host = (args.host or "").strip()
    port = int(args.port or 0)

    if not host and not getattr(args, "no_discover", False):
        from pc_modules.discovery import discover_car

        logger.info("listening udp://0.0.0.0:%s timeout=%.1fs", args.discover_port, args.discover_timeout)
        car = discover_car(timeout=args.discover_timeout, port=args.discover_port)
        if car:
            host = car.ip
            port = car.port
            logger.info("found %s at %s server_running=%s", car.name, car.uri, car.server_running)
        else:
            logger.warning("not found, fallback to default host")

    if not host:
        host = DEFAULT_CAR_HOST
    if not port:
        port = DEFAULT_CAR_PORT

    return RuntimeEndpoint(host=host, port=port, auth_token=resolve_auth_token(args.auth_token))
