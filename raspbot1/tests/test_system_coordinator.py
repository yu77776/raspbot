import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coordinator.system_coordinator import (
    AgentStatus,
    RuntimeEndpoint,
    SharedRuntimeState,
    SystemCoordinator,
    resolve_endpoint,
)
from pc_agents.pc_agent import PcAgent
from pc_agents.app_agent import AppAgent


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

    def test_coordinator_initial_status_all_idle(self):
        coordinator = SystemCoordinator(_args(), "token")
        self.assertEqual(
            coordinator.status,
            {"car": "IDLE", "pc": "IDLE", "app": "IDLE"},
        )

    def test_coordinator_all_healthy_when_idle(self):
        coordinator = SystemCoordinator(_args(), "token")
        self.assertTrue(coordinator.all_healthy)

    def test_agents_share_tracking_state(self):
        from pc_modules.app_gateway import TrackingModeStore
        from pc_modules.voice_cry_bridge import CryStateStore

        shared = SharedRuntimeState(
            cry_state=CryStateStore(),
            tracking_mode_store=TrackingModeStore(enabled=True),
        )
        endpoint = RuntimeEndpoint(host="127.0.0.1", port=5001, auth_token="token")
        args = _args()

        pc = PcAgent(args, endpoint, endpoint.auth_token, shared)
        app = AppAgent(args, endpoint, endpoint.auth_token, shared, pc.client)

        self.assertIs(pc.shared_state.tracking_mode_store, app.shared_state.tracking_mode_store)
        self.assertIs(pc.client, app.client)
        self.assertEqual(pc.client.uri, "ws://127.0.0.1:5001?token=token")

    def test_coordinator_wires_agents_correctly(self):
        endpoint = RuntimeEndpoint(host="10.0.0.1", port=5001, auth_token="tk")
        coordinator = SystemCoordinator(_args(), "tk")
        coordinator.run_with_endpoint(endpoint)
        # After run_with_endpoint returns (pc_agent.run() exits immediately
        # since the client isn't actually connected), agents should exist.
        self.assertIsNotNone(coordinator.pc_agent)
        self.assertIsNotNone(coordinator.app_agent)
        self.assertIsNotNone(coordinator.shared_state)
        # Agents share the tracking mode store
        self.assertIs(
            coordinator.pc_agent.shared_state.tracking_mode_store,
            coordinator.app_agent.shared_state.tracking_mode_store,
        )

    def test_agent_status_transitions(self):
        coordinator = SystemCoordinator(_args(), "token")
        self.assertEqual(coordinator.status["pc"], "IDLE")
        # Simulate a phase transition
        coordinator._phase("pc", AgentStatus.RUNNING)
        self.assertEqual(coordinator.status["pc"], "RUNNING")
        coordinator._phase("pc", AgentStatus.DEGRADED)
        self.assertFalse(coordinator.all_healthy)


if __name__ == "__main__":
    unittest.main()
