import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_modules.discovery import CarDiscovery
from agent_modules.launcher import (
    RemoteCar,
    RemoteResult,
    _ensure_auth_token,
    _iter_remote_sync_files,
    _load_cached_car,
    _save_cached_car,
    parse_args,
)


class LauncherSyncTest(unittest.TestCase):
    def test_car_sync_is_enabled_by_default_with_escape_hatch(self):
        old_argv = sys.argv[:]
        try:
            sys.argv = ["raspbot_agent.py"]
            self.assertFalse(parse_args().skip_car_sync)

            sys.argv = ["raspbot_agent.py", "--skip-car-sync"]
            self.assertTrue(parse_args().skip_car_sync)
        finally:
            sys.argv = old_argv

    def test_sync_file_filter_skips_cache_and_local_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keep = root / "car_server_modular.py"
            keep.write_text("print('ok')\n", encoding="utf-8")
            (root / "raspbot.local.json").write_text("{}\n", encoding="utf-8")
            cache_dir = root / "__pycache__"
            cache_dir.mkdir()
            (cache_dir / "car_server_modular.pyc").write_bytes(b"cache")

            synced = {p.relative_to(root).as_posix() for p in _iter_remote_sync_files(root)}

        self.assertEqual(synced, {"car_server_modular.py"})

    def test_car_cache_preserves_local_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raspbot.local.json"
            path.write_text('{"env":{"RASPBOT_SSH_PASSWORD":"yahboom"}}\n', encoding="utf-8")

            _save_cached_car(
                CarDiscovery(name="raspbot", ip="192.168.137.173", port=5001, server_running=True, hostname="pi"),
                path=path,
            )
            cached = _load_cached_car(5001, path=path)
            text = path.read_text(encoding="utf-8")

        self.assertIsNotNone(cached)
        self.assertEqual(cached.ip, "192.168.137.173")
        self.assertEqual(cached.port, 5001)
        self.assertIn("RASPBOT_SSH_PASSWORD", text)


class LauncherAuthTokenTest(unittest.TestCase):
    def setUp(self):
        self._old_token = os.environ.pop("RASPBOT_AUTH_TOKEN", None)
        self._old_allow_insecure = os.environ.pop("RASPBOT_ALLOW_INSECURE", None)

    def tearDown(self):
        for key in ("RASPBOT_AUTH_TOKEN", "RASPBOT_ALLOW_INSECURE"):
            os.environ.pop(key, None)
        if self._old_token is not None:
            os.environ["RASPBOT_AUTH_TOKEN"] = self._old_token
        if self._old_allow_insecure is not None:
            os.environ["RASPBOT_ALLOW_INSECURE"] = self._old_allow_insecure

    def test_missing_token_is_generated_and_persisted_for_launcher_and_android(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "raspbot.local.json"
            android_props = root / "local.properties"
            config_path.write_text('{"env":{"RASPBOT_SSH_PASSWORD":"yahboom"}}\n', encoding="utf-8")
            android_props.write_text("sdk.dir=E\\:\\\\Android\\\\Android SDK\n", encoding="utf-8")

            token = _ensure_auth_token("", config_path=config_path, android_properties_path=android_props)

            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            props = android_props.read_text(encoding="utf-8")

        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(os.environ["RASPBOT_AUTH_TOKEN"], token)
        self.assertEqual(cfg["env"]["RASPBOT_AUTH_TOKEN"], token)
        self.assertEqual(cfg["env"]["RASPBOT_SSH_PASSWORD"], "yahboom")
        self.assertIn(f"RASPBOT_AUTH_TOKEN={token}", props)

    def test_explicit_lab_insecure_skips_token_generation(self):
        os.environ["RASPBOT_ALLOW_INSECURE"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "raspbot.local.json"
            android_props = root / "local.properties"

            token = _ensure_auth_token("", config_path=config_path, android_properties_path=android_props)

            self.assertFalse(config_path.exists())
            self.assertFalse(android_props.exists())

        self.assertEqual(token, "")
        self.assertNotIn("RASPBOT_AUTH_TOKEN", os.environ)

    def test_remote_start_propagates_explicit_lab_insecure_flag(self):
        class CaptureRemote(RemoteCar):
            def __init__(self):
                self.command = ""

            def exec(self, command: str, timeout=None):
                self.command = command
                return RemoteResult(stdout="started", stderr="", exit_status=0)

        os.environ["RASPBOT_ALLOW_INSECURE"] = "1"
        remote = CaptureRemote()

        result = remote.start_server(auth_token="", heartbeat_timeout=0)

        self.assertEqual(result.exit_status, 0)
        self.assertIn("RASPBOT_ALLOW_INSECURE=1", remote.command)


if __name__ == "__main__":
    unittest.main()
