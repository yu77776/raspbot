"""PC runtime system coordinator."""

from dataclasses import dataclass
from typing import Optional

from pc_agents.app_agent import AppAgent
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


class SystemCoordinator:
    """Coordinates PC control and App-facing runtime agents."""

    def __init__(self, args, endpoint: RuntimeEndpoint):
        self.args = args
        self.endpoint = endpoint
        self.shared_state = SharedRuntimeState(
            cry_state=CryStateStore(),
            tracking_mode_store=TrackingModeStore(enabled=True),
        )
        self.pc_agent = PcAgent(args, endpoint, endpoint.auth_token, self.shared_state)
        self.app_agent = AppAgent(args, endpoint, endpoint.auth_token, self.shared_state, self.pc_agent.client)

    @classmethod
    def from_args(cls, args, *, endpoint: Optional[RuntimeEndpoint] = None):
        if endpoint is None:
            endpoint = resolve_endpoint(args)
        return cls(args, endpoint)

    def run(self) -> None:
        self.pc_agent.start()
        self.app_agent.start()
        try:
            self.pc_agent.run()
        finally:
            self.app_agent.stop()
            self.pc_agent.stop()


def resolve_endpoint(args) -> RuntimeEndpoint:
    host = (args.host or "").strip()
    port = int(args.port or 0)

    if not host and not args.no_discover:
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
