import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.asr_server import AsrServer, ServerConfig, _build_start_frame

_real_sleep = asyncio.sleep


class TestAsrCryDetectorIntegration(unittest.TestCase):
    def test_audio_frames_update_cry_state_before_forwarding_to_baidu(self):
        async def run():
            cry_updates = []

            class FakeCryDetector:
                def feed_pcm16(self, audio):
                    self.last_audio = bytes(audio)
                    return [(True, 0.75)]

            server = AsrServer(
                ServerConfig(
                    baidu_frame_ms=20,
                    on_cry_state=lambda crying, ratio: cry_updates.append((crying, ratio)),
                    cry_detector_factory=lambda: FakeCryDetector(),
                )
            )
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
                    return b"\x01\x00" * 320

            class FakeBaiduWs:
                async def send(self, payload):
                    sent_payloads.append(payload)

                async def close(self):
                    pass

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    return json.dumps({"err_no": -3005})

            class FakeConnect:
                async def __aenter__(self):
                    return FakeBaiduWs()

                async def __aexit__(self, *args):
                    return False

            with patch("pc_modules.asr_server.websockets.connect", return_value=FakeConnect()):
                await server._run_baidu_session(FakeClientWs())

            return cry_updates, sent_payloads

        cry_updates, sent_payloads = asyncio.run(run())
        self.assertIn((True, 0.75), cry_updates)
        self.assertTrue(any(isinstance(payload, (bytes, bytearray)) for payload in sent_payloads))


if __name__ == "__main__":
    unittest.main()
