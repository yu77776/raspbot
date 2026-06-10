import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_agents.car_agent import CarAgent
from pc_modules.discovery import CarDiscovery


def _args(**overrides):
    defaults = dict(
        skip_car_start=True,
        leave_car_running=False,
        remote_heartbeat_timeout=12.0,
        ssh_user="pi",
        ssh_password=None,
        trust_new_host_key=False,
        skip_car_sync=False,
        disable_asr=False,
        disable_mic_stream=False,
        no_tail=True,
        refresh_car_cache=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCarAgent(unittest.TestCase):
    def test_skip_car_start_only_resolves_car(self):
        car = CarDiscovery(name="raspbot", ip="10.0.0.5", port=5001, raw={"source": "explicit"})
        agent = CarAgent(_args(skip_car_start=True), auth_token="token")

        with patch("pc_modules.car_resolver.resolve_car", return_value=car):
            resolved = agent.start()

        self.assertIs(resolved, car)
        self.assertIs(agent.remote, None)
        self.assertFalse(agent.started_remote)

    def test_stop_does_not_stop_unstarted_remote(self):
        class FakeRemote:
            def __init__(self):
                self.stopped = False
                self.closed = False

            def stop_server(self):
                self.stopped = True

            def close(self):
                self.closed = True

        remote = FakeRemote()
        agent = CarAgent(_args(), auth_token="token")
        agent.remote = remote
        agent.started_remote = False

        agent.stop()

        self.assertFalse(remote.stopped)
        self.assertTrue(remote.closed)

    def test_disable_asr_disables_remote_mic_stream(self):
        class Result:
            exit_status = 0
            stdout = "started"
            stderr = ""

        class FakeRemote:
            last_kwargs = None

            def __init__(self, *args, **kwargs):
                pass

            def start_server(self, **kwargs):
                FakeRemote.last_kwargs = kwargs
                return Result()

            def close(self):
                pass

        car = CarDiscovery(name="raspbot", ip="10.0.0.5", port=5001, raw={"source": "explicit"})
        agent = CarAgent(
            _args(skip_car_start=False, skip_car_sync=True, leave_car_running=True, disable_asr=True),
            auth_token="token",
        )

        with patch("pc_modules.car_resolver.resolve_car", return_value=car), \
             patch("pc_modules.remote_car.RemoteCar", FakeRemote):
            agent.start()

        self.assertTrue(FakeRemote.last_kwargs["disable_mic_stream"])


if __name__ == "__main__":
    unittest.main()
