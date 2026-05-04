import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
REMOTE = REPO / "raspbot_remote"
if str(REMOTE) not in sys.path:
    sys.path.insert(0, str(REMOTE))

import modules.camera as camera_module
from modules.camera import Camera, CameraRestartStatus


class StuckThread:
    def __init__(self):
        self.join_calls = 0

    def is_alive(self):
        return True

    def join(self, timeout=None):
        self.join_calls += 1


class CameraRestartTest(unittest.TestCase):
    def test_stuck_capture_thread_requires_process_restart(self):
        old_has_camera = camera_module.HAS_CAMERA
        camera_module.HAS_CAMERA = True
        try:
            cam = object.__new__(Camera)
            cam.restart_lock = threading.Lock()
            cam.restart_cooldown_sec = 0.0
            cam._last_restart_t = 0.0
            cam.stop_event = threading.Event()
            cam.thread = StuckThread()
            cam.started = True
            cam.lock = threading.Lock()
            cam.latest_jpeg = b"old"
            cam.frame_seq = 42
            cam.fps = 30
            cam.frame_count = 10
            cam.fps_timer = time.time()

            closed = []
            opened = []
            started = []
            cam._close_camera = lambda: closed.append(True)
            cam._open_camera = lambda: opened.append(True)
            cam.start = lambda: started.append(True)

            status = cam.restart()

        finally:
            camera_module.HAS_CAMERA = old_has_camera

        self.assertEqual(status, CameraRestartStatus.FATAL)
        self.assertEqual(cam.thread.join_calls, 2)
        self.assertEqual(closed, [True])
        self.assertEqual(opened, [])
        self.assertEqual(started, [])
        self.assertEqual(cam.latest_jpeg, b"old")


if __name__ == "__main__":
    unittest.main()
