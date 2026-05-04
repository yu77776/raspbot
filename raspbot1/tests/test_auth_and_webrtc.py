import asyncio
import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.webrtc_bridge import WebRtcBridge, WebRtcBridgeConfig


class FakeGateway:
    def __init__(self):
        self.sent = []

    def _build_voice_command_from_obj(self, _payload):
        return None

    async def _send_to_car(self, payload):
        self.sent.append(payload)


class WebRtcCommandTest(unittest.TestCase):
    def test_offer_requires_token_before_peer_is_created(self):
        bridge = object.__new__(WebRtcBridge)
        bridge.cfg = WebRtcBridgeConfig(auth_token="secret")
        called = []

        async def accept_offer(_ws, payload):
            called.append(payload)

        bridge._accept_offer = accept_offer

        asyncio.run(bridge._handle_signal(None, json.dumps({
            "type": "webrtc_offer",
            "auth_token": "wrong",
            "sdp": "v=0",
        })))
        self.assertEqual(called, [])

        asyncio.run(bridge._handle_signal(None, json.dumps({
            "type": "webrtc_offer",
            "auth_token": "secret",
            "sdp": "v=0",
        })))
        self.assertEqual(len(called), 1)

    def test_text_command_requires_token_and_strips_it_before_forwarding(self):
        bridge = object.__new__(WebRtcBridge)
        bridge.cfg = WebRtcBridgeConfig(auth_token="secret")
        bridge._gateway = FakeGateway()

        asyncio.run(bridge._handle_command_message(json.dumps({
            "auth_token": "secret",
            "action": "forward",
            "speed": 60,
        })))

        self.assertEqual(len(bridge._gateway.sent), 1)
        forwarded = bridge._gateway.sent[0]
        self.assertEqual(forwarded[:1], b"\x02")
        payload = json.loads(forwarded[1:].decode("utf-8"))
        self.assertEqual(payload["action"], "forward")
        self.assertNotIn("auth_token", payload)

    def test_text_command_with_bad_token_is_not_forwarded(self):
        bridge = object.__new__(WebRtcBridge)
        bridge.cfg = WebRtcBridgeConfig(auth_token="secret")
        bridge._gateway = FakeGateway()

        asyncio.run(bridge._handle_command_message(json.dumps({
            "auth_token": "wrong",
            "action": "forward",
            "speed": 60,
        })))

        self.assertEqual(bridge._gateway.sent, [])


class ExposedAuthConfigTest(unittest.TestCase):
    def test_car_server_rejects_exposed_bind_without_auth_token(self):
        car_path = REPO / "raspbot_remote"
        sys.path.insert(0, str(car_path))
        try:
            from protocol import validate_auth_config

            with self.assertRaises(RuntimeError):
                validate_auth_config("0.0.0.0", "", component="car")
            with self.assertRaises(RuntimeError):
                validate_auth_config("", "", component="car")
            validate_auth_config("127.0.0.1", "", component="car")
            validate_auth_config("0.0.0.0", "secret", component="car")
        finally:
            try:
                sys.path.remove(str(car_path))
            except ValueError:
                pass


class CarControlOwnerTest(unittest.TestCase):
    def test_only_active_owner_disconnect_triggers_safe_stop(self):
        car_path = REPO / "raspbot_remote"
        sys.path.insert(0, str(car_path))
        try:
            from car_server_modular import CarServer

            server = object.__new__(CarServer)
            server._control_lock = threading.Lock()
            server._control_owner = None
            server._control_owner_until = 0.0
            server.control_lease_sec = 1.0
            server.command_timeout_sec = 0.8

            self.assertTrue(server._claim_control_owner("pc", is_app_source=False, now=10.0))
            self.assertFalse(server._claim_control_owner("monitor", is_app_source=False, now=10.1))
            self.assertFalse(server._release_control_owner("monitor"))
            self.assertTrue(server._release_control_owner("pc"))
        finally:
            try:
                sys.path.remove(str(car_path))
            except ValueError:
                pass


if __name__ == "__main__":
    unittest.main()
