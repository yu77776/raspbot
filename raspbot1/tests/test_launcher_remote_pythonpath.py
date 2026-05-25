import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_modules.discovery import CarDiscovery
from pc_modules.process_utils import build_pc_command
from pc_modules.remote_car import (
    REMOTE_SOURCE_DIR,
    RemoteCar,
    RemoteResult,
    _iter_remote_sync_files,
)


class CapturingRemoteCar(RemoteCar):
    def __init__(self):
        pass

    def exec(self, command: str, timeout=None):
        self.command = command
        self.timeout = timeout
        return RemoteResult(stdout="ok", stderr="", exit_status=0)


class TestRemoteLauncherPythonPath(unittest.TestCase):
    def test_start_server_does_not_depend_on_parent_pythonpath(self):
        remote = CapturingRemoteCar()

        remote.start_server(auth_token="token")

        self.assertNotIn("REMOTE_REAL_PARENT", remote.command)
        self.assertNotIn("REMOTE_LOGICAL_PARENT", remote.command)
        self.assertNotIn("REMOTE_PYTHONPATH", remote.command)
        self.assertIn('"$PYTHON_BIN" -u car_server_modular.py', remote.command)

    def test_remote_sync_files_stay_inside_car_source_dir(self):
        files = list(_iter_remote_sync_files(REMOTE_SOURCE_DIR))

        self.assertGreater(len(files), 0)
        for path in files:
            path.relative_to(REMOTE_SOURCE_DIR)
            self.assertNotIn("raspbot_common", path.parts)

    def test_pc_process_uses_module_entrypoint(self):
        car = CarDiscovery(name="raspbot", ip="10.0.0.5", port=5001, raw={})

        command = build_pc_command(car, auth_token="token", pc_extra="--disable-asr")

        self.assertIn("-m", command)
        self.assertIn("pc_modules.app", command)
        self.assertNotIn("pc_client_ws.py", command)
        self.assertIn("--auth-token", command)
        self.assertIn("token", command)
        self.assertIn("--disable-asr", command)


if __name__ == "__main__":
    unittest.main()
