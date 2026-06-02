"""App-facing runtime agent."""

import time

from pc_modules.logger_setup import setup_logger
from pc_modules.protocol import BackgroundService

logger = setup_logger("raspbot.app-agent")


class AppAgent:
    """Owns the App-facing WebRTC bridge service."""

    def __init__(self, args, endpoint, auth_token, shared_state, client):
        self.args = args
        self.endpoint = endpoint
        self.auth_token = auth_token
        self.shared_state = shared_state
        self.client = client
        self.webrtc_runner = None

    def start(self) -> None:
        self._start_webrtc_bridge()

    def stop(self) -> None:
        if self.webrtc_runner is not None:
            self.webrtc_runner.stop()
            logger.info("bridge stopped")

    @property
    def is_healthy(self) -> bool:
        """App agent is healthy if WebRTC bridge is either disabled or running without error."""
        if self.webrtc_runner is None:
            return True
        return self.webrtc_runner.is_running and self.webrtc_runner.error is None

    def _start_webrtc_bridge(self) -> None:
        if not self.args.enable_webrtc_bridge:
            return

        from pc_modules.webrtc_bridge import WebRtcBridge, WebRtcBridgeConfig

        webrtc_cfg = WebRtcBridgeConfig(
            signaling_url=self.args.webrtc_signaling_url,
            car_host=self.endpoint.host,
            car_port=self.endpoint.port,
            stun_url=self.args.webrtc_stun_url,
            turn_url=self.args.webrtc_turn_url,
            turn_username=self.args.webrtc_turn_username,
            turn_credential=self.args.webrtc_turn_credential,
            env_interval=self.args.webrtc_env_interval,
            cry_state=self.shared_state.cry_state,
            auth_token=self.auth_token,
            tracking_mode_store=self.shared_state.tracking_mode_store,
        )
        self.webrtc_runner = BackgroundService(
            lambda: WebRtcBridge(
                webrtc_cfg,
                self.client.get_latest_webrtc_frame,
                self.client.get_latest_env_dict,
            ),
            name="raspbot.webrtc",
        )
        self.webrtc_runner.start()
        time.sleep(0.3)
        if self.webrtc_runner.error is not None:
            logger.error("bridge failed: %s", self.webrtc_runner.error)
            logger.warning("tip: install aiortc or disable with no --enable-webrtc-bridge")
        else:
            logger.info("bridge started via %s", self.args.webrtc_signaling_url)
