import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT.parent / "raspbot_remote"
if str(REMOTE) not in sys.path:
    sys.path.insert(0, str(REMOTE))

from coordinator import runtime_launcher
from modules import buzzer as buzzer_module
from modules.buzzer import Buzzer


class FakePwm:
    def __init__(self):
        self.values = []

    def ChangeDutyCycle(self, value):
        self.values.append(value)


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


if __name__ == "__main__":
    unittest.main()
