#!/usr/bin/env python3
"""Camera capture module for WebSocket JPEG streaming."""
import concurrent.futures
import os
import threading
import time
from enum import Enum

import cv2
import numpy as np

from logger_setup import setup_logger

logger = setup_logger('raspbot.camera')


class CameraRestartStatus(Enum):
    OK = "ok"
    SKIPPED = "skipped"
    FATAL = "fatal"

try:
    from picamera2 import Picamera2
    HAS_CAMERA = True
except ImportError:
    Picamera2 = None
    HAS_CAMERA = False


class Camera:
    def __init__(
        self,
        width=640,
        height=480,
        quality=80,
        framerate=20,
    ):
        self.width = int(width)
        self.height = int(height)
        self.quality = int(quality)
        self.framerate = int(framerate)

        self.latest_jpeg = b''
        self.frame_seq = 0
        self.fps = 0
        self.frame_count = 0
        self.fps_timer = time.time()

        self.lock = threading.Lock()
        self.restart_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.thread = None
        self.started = False
        self.restart_cooldown_sec = float(os.getenv('RASPBOT_CAMERA_RESTART_COOLDOWN_SEC', '6'))
        self.capture_timeout = float(os.getenv('RASPBOT_CAMERA_CAPTURE_TIMEOUT', '3.0'))
        self._last_restart_t = 0.0
        self._capture_executor = None

        self.picam2 = None

        if HAS_CAMERA:
            self._open_camera()
            logger.info('init ok size=%sx%s fps=%s', self.width, self.height, self.framerate)
        else:
            logger.warning('picamera2 unavailable, use placeholder frames')

    def _open_camera(self):
        if not HAS_CAMERA:
            return
        self.picam2 = Picamera2()
        config = self.picam2.create_video_configuration(
            main={'format': 'YUV420', 'size': (self.width, self.height)},
            controls={'FrameRate': self.framerate},
        )
        self.picam2.configure(config)

    def _close_camera(self):
        if not HAS_CAMERA or self.picam2 is None:
            return
        old = self.picam2
        self.picam2 = None

        def _do_close():
            try:
                old.stop()
            except Exception:
                pass
            try:
                old.close()
            except Exception:
                pass

        t = threading.Thread(target=_do_close, daemon=True)
        t.start()
        t.join(timeout=2.0)
        if t.is_alive():
            logger.warning('camera close timed out; abandoning old picam2 handle')

    def _make_placeholder(self):
        img = np.zeros((self.height, self.width, 3), dtype='uint8')
        cv2.putText(
            img,
            'NO CAMERA',
            (self.width // 4, self.height // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (0, 200, 255),
            3,
        )
        return img

    def _frame_to_bgr(self, frame):
        if frame is None:
            return None
        if len(frame.shape) == 2:
            return cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
        return frame

    def _run(self):
        placeholder = None
        if HAS_CAMERA:
            try:
                if self.picam2 is None:
                    self._open_camera()
                self.picam2.start()
                self.ready_event.set()
            except Exception as exc:
                logger.exception('camera start failed: %s', exc)
                self.ready_event.clear()
                return
        else:
            placeholder = self._make_placeholder()
            self.ready_event.set()

        if HAS_CAMERA and self._capture_executor is None:
            self._capture_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        while not self.stop_event.is_set():
            loop_start = time.time()
            try:
                if HAS_CAMERA:
                    if self.picam2 is None:
                        self.stop_event.wait(0.1)
                        continue
                    future = self._capture_executor.submit(self.picam2.capture_array, 'main')
                    frame = future.result(timeout=self.capture_timeout)
                else:
                    frame = placeholder
                frame = self._frame_to_bgr(frame)
                ret, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
                if ret:
                    with self.lock:
                        self.latest_jpeg = buf.tobytes()
                        self.frame_seq += 1
                        self.frame_count += 1
                        if time.time() - self.fps_timer >= 1.0:
                            self.fps = self.frame_count
                            self.frame_count = 0
                            self.fps_timer = time.time()
            except concurrent.futures.TimeoutError:
                logger.warning('camera capture timed out after %.1fs', self.capture_timeout)
                continue
            except Exception as e:
                logger.warning('frame loop error: %s', e)
                self.stop_event.wait(0.1)
                continue

            target_period = 1.0 / max(5, self.framerate)
            elapsed = time.time() - loop_start
            time.sleep(max(0.0, target_period - elapsed))

        if self._capture_executor is not None:
            self._capture_executor.shutdown(wait=False)
            self._capture_executor = None

        self._close_camera()
        self.ready_event.clear()

    def start(self):
        if self.started and self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.ready_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        if HAS_CAMERA:
            self.ready_event.wait(timeout=2.0)
        self.started = True

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self._capture_executor is not None:
            self._capture_executor.shutdown(wait=False)
            self._capture_executor = None
        self.started = False

    def restart(self):
        if not self.restart_lock.acquire(blocking=False):
            logger.warning('restart already in progress; skip duplicate request')
            return CameraRestartStatus.SKIPPED
        try:
            now = time.monotonic()
            if self.restart_cooldown_sec > 0 and now - self._last_restart_t < self.restart_cooldown_sec:
                logger.warning('restart requested during cooldown; skip duplicate request')
                return CameraRestartStatus.SKIPPED
            self._last_restart_t = now

            logger.info('restarting camera module')
            self.stop_event.set()
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=2.0)
            if self.thread and self.thread.is_alive():
                logger.warning('capture thread did not exit; closing camera to unblock it')
                self._close_camera()
                self.thread.join(timeout=2.0)
            was_stuck = self.thread and self.thread.is_alive()
            if was_stuck:
                logger.error('capture thread still alive after forced close; process restart required')
                return CameraRestartStatus.FATAL

            self.thread = None
            self.started = False
            with self.lock:
                self.latest_jpeg = b''
                self.frame_seq = 0
                self.fps = 0
                self.frame_count = 0
                self.fps_timer = time.time()
            self._close_camera()
            try:
                if HAS_CAMERA:
                    self._open_camera()
                self.start()
            except Exception as exc:
                logger.exception('camera restart failed: %s', exc)
                return CameraRestartStatus.FATAL
            return CameraRestartStatus.OK
        finally:
            self.restart_lock.release()

    def get_fps(self):
        with self.lock:
            return self.fps

    def get_frame(self):
        with self.lock:
            return self.frame_seq, self.latest_jpeg


if __name__ == '__main__':
    print('Testing camera module...')
    cam = Camera()
    cam.start()
    for _ in range(10):
        seq, jpeg = cam.get_frame()
        print(f'Frame {seq}: {len(jpeg)} bytes')
        time.sleep(0.5)
    cam.stop()
