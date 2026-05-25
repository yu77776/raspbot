import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coordinator.system_coordinator import RuntimeEndpoint, SystemCoordinator, resolve_endpoint


def _args(**overrides):
    defaults = dict(
        host="",
        port=0,
        no_discover=True,
        discover_port=5002,
        discover_timeout=0.1,
        auth_token="token",
        model="best.pt",
        yolo_device="cpu",
        yolo_use_cudnn=False,
        tuning="",
        disable_asr=True,
        asr_host="127.0.0.1",
        asr_port=6006,
        asr_path="/audio",
        asr_window_sec=2.0,
        asr_step_sec=1.0,
        asr_silence_rms=220,
        baidu_appid="",
        baidu_api_key="",
        baidu_secret_key="",
        baidu_access_token="",
        baidu_url="wss://example",
        baidu_dev_pid=15372,
        baidu_cuid="raspbot-pc",
        baidu_lm_id="",
        baidu_user="",
        baidu_frame_ms=160,
        baidu_emit_partial=False,
        enable_webrtc_bridge=False,
        webrtc_signaling_url="ws://example",
        webrtc_stun_url="stun:example",
        webrtc_turn_url="turn:example",
        webrtc_turn_username="user",
        webrtc_turn_credential="",
        webrtc_env_interval=0.2,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestSystemCoordinator(unittest.TestCase):
    def test_resolve_endpoint_uses_defaults_without_discovery(self):
        endpoint = resolve_endpoint(_args())

        self.assertEqual(endpoint.host, "10.188.152.100")
        self.assertEqual(endpoint.port, 5001)
        self.assertEqual(endpoint.auth_token, "token")

    def test_coordinator_shares_tracking_state_between_agents(self):
        endpoint = RuntimeEndpoint(host="127.0.0.1", port=5001, auth_token="token")
        coordinator = SystemCoordinator(_args(), endpoint)

        self.assertIs(
            coordinator.pc_agent.shared_state.tracking_mode_store,
            coordinator.app_agent.shared_state.tracking_mode_store,
        )
        self.assertIs(coordinator.pc_agent.client, coordinator.app_agent.client)
        self.assertEqual(coordinator.pc_agent.client.uri, "ws://127.0.0.1:5001?token=token")


if __name__ == "__main__":
    unittest.main()
