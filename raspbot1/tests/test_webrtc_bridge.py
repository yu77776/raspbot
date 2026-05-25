import asyncio
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.webrtc_bridge import (
    WebRtcBridge,
    WebRtcBridgeConfig,
    _is_aiortc_disconnect_noise,
)
from pc_modules.app_gateway import AppGateway, GatewayConfig
from pc_modules import settings as cfg
from pc_modules.voice_cry_bridge import CryStateStore


class FakePeer:
    connectionState = "connected"
    iceConnectionState = "connected"


class FakeChannel:
    readyState = "open"

    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


class TestWebRtcBridgeDisconnectHandling(unittest.TestCase):
    def test_suppresses_known_aiortc_disconnect_noise(self):
        self.assertTrue(
            _is_aiortc_disconnect_noise(
                {"exception": ConnectionError("Cannot send data, not connected")}
            )
        )
        self.assertFalse(
            _is_aiortc_disconnect_noise({"exception": RuntimeError("other failure")})
        )

    def test_env_loop_is_bound_to_current_peer(self):
        async def run():
            bridge = object.__new__(WebRtcBridge)
            bridge.cfg = WebRtcBridgeConfig(env_interval=0.01)
            bridge._pc = FakePeer()
            stale_peer = FakePeer()
            channel = FakeChannel()
            bridge._env_channel = channel
            bridge._env_provider = lambda: {"temp": 1}
            bridge._merge_env_cry = lambda payload: payload

            await bridge._env_loop(stale_peer)
            return channel.sent

        self.assertEqual(asyncio.run(run()), [])

    def test_env_loop_stops_when_peer_disconnects(self):
        async def run():
            bridge = object.__new__(WebRtcBridge)
            bridge.cfg = WebRtcBridgeConfig(env_interval=0.01)
            peer = FakePeer()
            peer.connectionState = "disconnected"
            bridge._pc = peer
            channel = FakeChannel()
            bridge._env_channel = channel
            bridge._env_provider = lambda: {"temp": 1}
            bridge._merge_env_cry = lambda payload: payload

            await bridge._env_loop(peer)
            return channel.sent

        self.assertEqual(asyncio.run(run()), [])


class TestAppGatewayTrackingMode(unittest.TestCase):
    def test_tracking_mode_string_false_is_false(self):
        gateway = AppGateway(GatewayConfig())

        packet = bytes([0x02]) + b'{"tracking_mode":"false"}'

        self.assertFalse(gateway._extract_tracking_mode(packet))

    def test_tracking_mode_string_zero_is_false(self):
        gateway = AppGateway(GatewayConfig())

        packet = bytes([0x02]) + b'{"tracking_mode":"0"}'

        self.assertFalse(gateway._extract_tracking_mode(packet))

    def test_tracking_mode_string_true_is_true(self):
        gateway = AppGateway(GatewayConfig())

        packet = bytes([0x02]) + b'{"tracking_mode":"true"}'

        self.assertTrue(gateway._extract_tracking_mode(packet))

    def test_app_auto_tracking_packet_is_not_forwarded_to_car(self):
        async def run():
            gateway = AppGateway(GatewayConfig())
            sent = []

            class FakeWs:
                async def send(self, payload):
                    sent.append(payload)

            gateway._car_ws = FakeWs()
            gateway._car_ready.set()
            packet = bytes([0x02]) + b'{"source":"app_auto","tracking_mode":true,"action":"stop"}'

            await gateway._send_to_car(packet)
            return sent, gateway.is_tracking_enabled()

        sent, enabled = asyncio.run(run())
        self.assertEqual(sent, [])
        self.assertTrue(enabled)


class TestAppGatewayCrySync(unittest.TestCase):
    def test_periodic_sync_sends_cry_state_to_car(self):
        async def run():
            cry_state = CryStateStore()
            cry_state.update_from_ratio(True, 0.91)
            gateway = AppGateway(GatewayConfig(cry_state=cry_state))

            class FakeCarWs:
                def __init__(self):
                    self.sent = []

                async def send(self, payload):
                    self.sent.append(payload)
                    raise asyncio.CancelledError()

            car_ws = FakeCarWs()
            with self.assertRaises(asyncio.CancelledError):
                await gateway._cry_state_sync_loop(car_ws)
            return car_ws.sent

        sent = asyncio.run(run())
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], cfg.MSG_COMMAND)
        payload = json.loads(sent[0][1:].decode("utf-8"))
        self.assertEqual(payload["source"], "cry_sync")
        self.assertEqual(payload["remote_crying"], True)
        self.assertEqual(payload["remote_cry_score"], 91)
        self.assertEqual(payload["remote_alarm"], "cry")


if __name__ == "__main__":
    unittest.main()
