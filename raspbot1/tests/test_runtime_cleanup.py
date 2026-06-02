import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT.parent / "raspbot_remote"
if str(REMOTE) not in sys.path:
    sys.path.insert(0, str(REMOTE))

from coordinator import runtime_launcher
from car_server_modular import CarServer
from modules import buzzer as buzzer_module
from modules.buzzer import Buzzer


class FakePwm:
    def __init__(self):
        self.values = []

    def ChangeDutyCycle(self, value):
        self.values.append(value)


class BlockingMotor:
    def __init__(self):
        self.stop_calls = 0
        self.center_calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def stop(self):
        self.stop_calls += 1
        self.entered.set()
        self.release.wait(timeout=1.0)

    def center_servos(self, *_args, **_kwargs):
        self.center_calls += 1


class TestRuntimeCleanup(unittest.TestCase):
    def test_wait_websocket_dead_code_removed(self):
        self.assertFalse(hasattr(runtime_launcher, "wait_websocket"))

    def test_buzzer_pattern_reuses_single_worker(self):
        buzzer = Buzzer.__new__(Buzzer)
        buzzer.enabled = True
        buzzer._pwm = FakePwm()
        buzzer.pwm_duty = 50
        buzzer.lock = buzzer_module.threading.Lock()
        buzzer.stop_event = buzzer_module.threading.Event()
        buzzer._pattern_lock = buzzer_module.threading.Lock()
        buzzer._pattern_thread = None
        buzzer._pattern_cancel = buzzer_module.threading.Event()

        buzzer.beep_pattern(4, 0.05, 0.05)
        first_thread = buzzer._pattern_thread
        buzzer.beep_pattern(1, 0.001, 0.001)
        second_thread = buzzer._pattern_thread
        second_thread.join(timeout=1.0)

        self.assertIsNot(first_thread, second_thread)
        self.assertFalse(second_thread.is_alive())
        buzzer._pattern_cancel.set()
        first_thread.join(timeout=1.0)
        self.assertFalse(first_thread.is_alive())

    def test_safe_stop_motion_skips_reentrant_call(self):
        server = CarServer.__new__(CarServer)
        server.motor = BlockingMotor()
        server.home_servos_on_safe_stop = True
        server._safe_stop_lock = threading.Lock()
        server._safe_stop_in_progress = False

        first = threading.Thread(target=server._safe_stop_motion, args=("watchdog-1",), daemon=True)
        first.start()
        self.assertTrue(server.motor.entered.wait(timeout=1.0))

        server._safe_stop_motion("watchdog-2")
        server.motor.release.set()
        first.join(timeout=1.0)

        self.assertEqual(server.motor.stop_calls, 1)
        self.assertEqual(server.motor.center_calls, 1)
        self.assertFalse(server._safe_stop_in_progress)


if __name__ == "__main__":
    unittest.main()
