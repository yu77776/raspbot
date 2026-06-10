import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.asr_server import (
    AsrServer,
    ServerConfig,
    _AUDIO_EOF,
    _fetch_access_token,
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


class TestBaiduTokenFetch(unittest.TestCase):
    def test_fetch_token_uses_form_post(self):
        captured = {}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"access_token":"token-1"}'

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["data"] = req.data
            captured["content_type"] = req.headers.get("Content-type")
            captured["method"] = req.get_method()
            captured["timeout"] = timeout
            return FakeResp()

        with patch("pc_modules.asr_server.urlopen", fake_urlopen):
            token = _fetch_access_token("api", "secret")

        self.assertEqual(token, "token-1")
        self.assertEqual(captured["url"], "https://aip.baidubce.com/oauth/2.0/token")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["content_type"], "application/x-www-form-urlencoded")
        self.assertIn(b"grant_type=client_credentials", captured["data"])
        self.assertIn(b"client_id=api", captured["data"])
        self.assertIn(b"client_secret=secret", captured["data"])

    def test_fetch_token_falls_back_to_curl_on_url_error(self):
        class FakeResult:
            returncode = 0
            stdout = '{"access_token":"curl-token"}'
            stderr = ""

        def fake_urlopen(_req, timeout):
            raise URLError("ssl eof")

        with patch("pc_modules.asr_server.urlopen", fake_urlopen), \
                patch("pc_modules.asr_server.subprocess.run", return_value=FakeResult()) as run:
            token = _fetch_access_token("api", "secret")

        self.assertEqual(token, "curl-token")
        args = run.call_args.args[0]
        self.assertIn("curl.exe", args[0])
        self.assertIn("--data", args)


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

    def test_handle_client_keeps_mic_connection_after_transient_baidu_error(self):
        async def run():
            class TestServer(AsrServer):
                def __init__(self):
                    super().__init__(ServerConfig())
                    self.calls = 0

                async def _run_baidu_session_from_queue(self, audio_queue):
                    self.calls += 1
                    if self.calls == 1:
                        await audio_queue.get()
                        raise asyncio.TimeoutError()
                    while True:
                        item = await audio_queue.get()
                        if item is _AUDIO_EOF:
                            return False

            class FakeWs:
                path = "/audio"
                remote_address = ("car", 5001)

                def __init__(self):
                    self.count = 0

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if self.count >= 1:
                        raise StopAsyncIteration
                    self.count += 1
                    await _real_sleep(0)
                    return b"\x00" * 640

                async def close(self, *_args):
                    raise AssertionError("mic websocket should stay open for transient Baidu errors")

            server = TestServer()
            await server.handle_client(FakeWs())
            return server.calls

        self.assertEqual(asyncio.run(run()), 2)

    def test_handle_client_backs_off_and_drops_stale_audio_on_repeated_baidu_errors(self):
        async def run():
            sleep_delays = []
            original_sleep = asyncio.sleep

            async def fake_sleep(delay):
                sleep_delays.append(delay)
                await original_sleep(0)

            class TestServer(AsrServer):
                def __init__(self):
                    super().__init__(ServerConfig())
                    self.calls = 0
                    self.queue_sizes = []

                async def _run_baidu_session_from_queue(self, audio_queue):
                    self.calls += 1
                    self.queue_sizes.append(audio_queue.qsize())
                    if self.calls <= 3:
                        raise ConnectionResetError()
                    while True:
                        item = await audio_queue.get()
                        if item is _AUDIO_EOF:
                            return False

            class FakeWs:
                path = "/audio"
                remote_address = ("car", 5001)

                def __init__(self):
                    self.count = 0

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if self.count >= 140:
                        raise StopAsyncIteration
                    self.count += 1
                    await _real_sleep(0)
                    return b"\x00" * 640

                async def close(self, *_args):
                    raise AssertionError("mic websocket should stay open for transient Baidu errors")

            server = TestServer()
            with patch("pc_modules.asr_server.asyncio.sleep", fake_sleep):
                await server.handle_client(FakeWs())
            return sleep_delays, server.queue_sizes

        sleep_delays, queue_sizes = asyncio.run(run())
        self.assertEqual(sleep_delays[:3], [0.5, 1.0, 2.0])
        self.assertLessEqual(max(queue_sizes), 96)
        self.assertLess(queue_sizes[-1], 96)


if __name__ == "__main__":
    unittest.main()
