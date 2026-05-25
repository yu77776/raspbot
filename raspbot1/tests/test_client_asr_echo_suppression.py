import sys
import unittest
import asyncio
import json
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.client import PCClientWS
from pc_modules.dialogue_engine import DialogueReply


class FakeDialogue:
    def __init__(self):
        self.calls = []

    def respond(self, text):
        self.calls.append(text)
        return DialogueReply(text="你好呀！有什么我可以帮你的吗？")


class TestAsrEchoSuppression(unittest.TestCase):
    def test_chat_reply_suppresses_followup_echo_text(self):
        client = PCClientWS(uri="ws://example", model_path="best.pt")
        client.dialogue = FakeDialogue()
        client._asr_echo_suppress_sec = 30.0

        client.on_asr_text("你好")
        client.on_asr_text("你好啊，有什么我可以帮你的吗？")

        self.assertEqual(client.dialogue.calls, ["你好"])

    def test_suppression_does_not_block_first_user_text(self):
        client = PCClientWS(uri="ws://example", model_path="best.pt")
        client.dialogue = FakeDialogue()
        client._asr_echo_suppress_until = 0.0

        client.on_asr_text("你好")

        self.assertEqual(client.dialogue.calls, ["你好"])
        self.assertGreater(client._asr_echo_suppress_until, 0.0)


class TestTrackingModeGate(unittest.TestCase):
    def test_tracking_disabled_returns_stop_command(self):
        client = PCClientWS(
            uri="ws://example",
            model_path="best.pt",
            tracking_enabled_provider=lambda: False,
        )
        client._last_track_locked = True
        client._last_track_conf = 0.8

        cmd = client.make_command({"boxes": [[1, 2, 3, 4]], "confs": [0.9], "classes": [0]})

        self.assertEqual(cmd.action, "stop")
        self.assertEqual(cmd.speed, 0)
        self.assertEqual(cmd.left_speed, 0)
        self.assertEqual(cmd.right_speed, 0)
        self.assertFalse(cmd.detecting)
        self.assertFalse(cmd.tracking_mode)
        self.assertFalse(client._last_track_locked)
        self.assertEqual(client._last_track_conf, 0.0)

    def test_tracking_provider_error_fails_closed(self):
        def broken_provider():
            raise RuntimeError("provider failed")

        client = PCClientWS(
            uri="ws://example",
            model_path="best.pt",
            tracking_enabled_provider=broken_provider,
        )

        cmd = client.make_command({})

        self.assertEqual(cmd.action, "stop")
        self.assertEqual(cmd.speed, 0)
        self.assertFalse(cmd.detecting)

    def test_tracking_disabled_log_only_on_state_change(self):
        client = PCClientWS(
            uri="ws://example",
            model_path="best.pt",
            tracking_enabled_provider=lambda: False,
        )

        with self.assertLogs("raspbot.client", level="INFO") as captured:
            self.assertFalse(client._tracking_enabled())
            self.assertFalse(client._tracking_enabled())

        messages = [record.getMessage() for record in captured.records]
        self.assertEqual(messages.count("tracking disabled by App; hold stop"), 1)

    def test_tracking_enabled_logs_resume_after_disabled_state(self):
        states = iter([False, True])
        client = PCClientWS(
            uri="ws://example",
            model_path="best.pt",
            tracking_enabled_provider=lambda: next(states),
        )

        with self.assertLogs("raspbot.client", level="INFO") as captured:
            self.assertFalse(client._tracking_enabled())
            self.assertTrue(client._tracking_enabled())

        messages = [record.getMessage() for record in captured.records]
        self.assertIn("tracking disabled by App; hold stop", messages)
        self.assertIn("tracking enabled by App", messages)

    def test_send_loop_keeps_sending_stop_when_tracking_disabled(self):
        class FakeWs:
            def __init__(self):
                self.sent = []

            async def send(self, payload):
                self.sent.append(payload)
                raise asyncio.CancelledError()

        async def run():
            client = PCClientWS(
                uri="ws://example",
                model_path="best.pt",
                tracking_enabled_provider=lambda: False,
            )
            ws = FakeWs()
            try:
                await client._send_loop(ws)
            except asyncio.CancelledError:
                pass
            return ws.sent

        sent = asyncio.run(run())
        self.assertEqual(len(sent), 1)
        payload = sent[0]
        self.assertEqual(payload[0], 0x02)
        command = json.loads(payload[1:].decode("utf-8"))
        self.assertEqual(command["action"], "stop")
        self.assertEqual(command["speed"], 0)
        self.assertEqual(command["left_speed"], 0)
        self.assertEqual(command["right_speed"], 0)


if __name__ == "__main__":
    unittest.main()
