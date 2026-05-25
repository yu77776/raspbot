import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.asr_server import (
    AsrServer,
    ServerConfig,
    _build_start_frame,
)

_real_sleep = asyncio.sleep


class TestBaiduStartFrame(unittest.TestCase):
    def test_start_frame_includes_numeric_appid(self):
        frame = json.loads(
            _build_start_frame(15372, "raspbot-pc", appid="123066238", appkey="key")
        )

        self.assertEqual(frame["data"]["appid"], 123066238)
        self.assertEqual(frame["data"]["appkey"], "key")
        self.assertEqual(frame["data"]["dev_pid"], 15372)

    def test_start_frame_rejects_non_numeric_appid(self):
        with self.assertRaisesRegex(RuntimeError, "BAIDU_APPID must be numeric"):
            _build_start_frame(15372, "raspbot-pc", appid="abc")


class TestAsrServerAudioGate(unittest.TestCase):
    def test_buffers_full_frame_before_baidu_connect(self):
        async def run():
            server = AsrServer(ServerConfig(baidu_frame_ms=160))
            sent_payloads = []

            async def fake_token():
                return "token"

            async def fake_start():
                return _build_start_frame(15372, "raspbot-pc", appid="123")

            server._get_access_token = fake_token
            server._build_start_frame = fake_start

            class FakeClientWs:
                def __init__(self):
                    self.count = 0

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if self.count >= 8:
                        raise StopAsyncIteration
                    self.count += 1
                    await _real_sleep(0)
                    return bytes([self.count]) * 640

            class FakeBaiduWs:
                async def send(self, payload):
                    sent_payloads.append(payload)

                async def close(self):
                    pass

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    await _real_sleep(0)
                    raise StopAsyncIteration

            class FakeConnect:
                async def __aenter__(self):
                    return FakeBaiduWs()

                async def __aexit__(self, *args):
                    return False

            with patch("pc_modules.asr_server.websockets.connect", return_value=FakeConnect()):
                await server._run_baidu_session(FakeClientWs())

            audio_frames = [
                payload for payload in sent_payloads if isinstance(payload, (bytes, bytearray))
            ]
            return sent_payloads, audio_frames

        sent_payloads, audio_frames = asyncio.run(run())
        self.assertGreaterEqual(len(sent_payloads), 2)
        self.assertEqual(len(audio_frames), 1)
        self.assertEqual(len(audio_frames[0]), 5120)

    def test_no_baidu_connect_when_audio_never_reaches_frame(self):
        async def run():
            server = AsrServer(ServerConfig(baidu_frame_ms=160))
            connect_calls = 0

            class ShortClientWs:
                def __init__(self):
                    self.count = 0

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if self.count >= 2:
                        raise StopAsyncIteration
                    self.count += 1
                    await _real_sleep(0)
                    return b"\x00" * 640

            def fake_connect(*_args, **_kwargs):
                nonlocal connect_calls
                connect_calls += 1
                raise AssertionError("Baidu should not connect before a full audio frame")

            with patch("pc_modules.asr_server.websockets.connect", side_effect=fake_connect):
                await server._run_baidu_session(ShortClientWs())
            return connect_calls

        self.assertEqual(asyncio.run(run()), 0)

    def test_no_effective_speech_keeps_client_session_alive(self):
        async def run():
            server = AsrServer(ServerConfig(baidu_frame_ms=20))
            sent_payloads = []

            async def fake_token():
                return "token"

            async def fake_start():
                return _build_start_frame(15372, "raspbot-pc", appid="123")

            server._get_access_token = fake_token
            server._build_start_frame = fake_start

            class FakeClientWs:
                def __init__(self):
                    self.count = 0

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if self.count >= 2:
                        raise StopAsyncIteration
                    self.count += 1
                    await _real_sleep(0)
                    return b"\x00" * 640

            class FakeBaiduWs:
                async def send(self, payload):
                    sent_payloads.append(payload)

                async def close(self):
                    pass

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    return '{"err_no": -3005, "err_msg": "asr server not find effective speech"}'

            class FakeConnect:
                async def __aenter__(self):
                    return FakeBaiduWs()

                async def __aexit__(self, *args):
                    return False

            with patch("pc_modules.asr_server.websockets.connect", return_value=FakeConnect()):
                keep_client_open = await server._run_baidu_session(FakeClientWs())

            return keep_client_open, sent_payloads

        keep_client_open, sent_payloads = asyncio.run(run())
        self.assertTrue(keep_client_open)
        self.assertGreaterEqual(len(sent_payloads), 1)


if __name__ == "__main__":
    unittest.main()
