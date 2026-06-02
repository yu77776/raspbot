"""PC-side control runtime agent."""

import asyncio
import time

from pc_modules.client import PCClientWS
from pc_modules.logger_setup import setup_logger
from pc_modules.protocol import BackgroundService

logger = setup_logger("raspbot.pc-agent")


class PcAgent:
    """Owns PC control client and ASR service."""

    def __init__(self, args, endpoint, auth_token, shared_state):
        self.args = args
        self.endpoint = endpoint
        self.auth_token = auth_token
        self.shared_state = shared_state
        self.client = self._build_client()
        self.asr_runner = None

    def start(self) -> None:
        self._start_asr()

    def run(self) -> None:
        asyncio.run(self.client.run())

    def stop(self) -> None:
        if self.asr_runner is not None:
            self.asr_runner.stop()
            logger.info("embedded server stopped")

    @property
    def is_healthy(self) -> bool:
        """PC agent is healthy only if the control client and optional ASR are OK."""
        if not self.client.is_healthy:
            return False
        if self.asr_runner is None:
            return True
        return self.asr_runner.is_running and self.asr_runner.error is None

    def _tracking_enabled(self) -> bool:
        return self.shared_state.tracking_mode_store.is_enabled()

    def _build_client(self) -> PCClientWS:
        return PCClientWS(
            uri=self.endpoint.auth_uri,
            model_path=self.args.model,
            yolo_device=self.args.yolo_device,
            yolo_disable_cudnn=not self.args.yolo_use_cudnn,
            tuning_path=self.args.tuning or None,
            tracking_enabled_provider=self._tracking_enabled,
        )

    def _start_asr(self) -> None:
        if self.args.disable_asr:
            return

        from pc_modules.asr_server import AsrServer, ServerConfig

        asr_cfg = ServerConfig(
            host=self.args.asr_host,
            port=self.args.asr_port,
            path=self.args.asr_path,
            window_sec=self.args.asr_window_sec,
            step_sec=self.args.asr_step_sec,
            silence_rms=self.args.asr_silence_rms,
            baidu_appid=self.args.baidu_appid,
            baidu_api_key=self.args.baidu_api_key,
            baidu_secret_key=self.args.baidu_secret_key,
            baidu_access_token=self.args.baidu_access_token,
            baidu_url=self.args.baidu_url,
            baidu_dev_pid=self.args.baidu_dev_pid,
            baidu_cuid=self.args.baidu_cuid,
            baidu_lm_id=self.args.baidu_lm_id,
            baidu_user=self.args.baidu_user,
            baidu_frame_ms=self.args.baidu_frame_ms,
            baidu_emit_partial=self.args.baidu_emit_partial,
            on_text=self.client.on_asr_text,
            on_cry_state=self.shared_state.cry_state.update_from_ratio,
        )
        self.asr_runner = BackgroundService(lambda: AsrServer(asr_cfg), name="raspbot.asr")
        self.asr_runner.start()
        time.sleep(0.3)
        if self.asr_runner.error is not None:
            logger.error("embedded server failed: %s", self.asr_runner.error)
            logger.warning("tip: stop existing asr_server.py or use --disable-asr")
        else:
            logger.info("embedded server started at ws://%s:%s%s", self.args.asr_host, self.args.asr_port, self.args.asr_path)
