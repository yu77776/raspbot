#!/usr/bin/env python3
"""Camera capture module for WebSocket JPEG streaming."""
import threading
import time

import cv2
import numpy as np

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
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.thread = None
        self.started = False

        self.picam2 = None

        if HAS_CAMERA:
            self.picam2 = Picamera2()
            config = self.picam2.create_video_configuration(
                main={'format': 'YUV420', 'size': (self.width, self.height)},
                controls={'FrameRate': self.framerate},
            )
            self.picam2.configure(config)
            print(f'[CAM] init ok size={self.width}x{self.height} fps={self.framerate}')
        else:
            print('[CAM] picamera2 unavailable, use placeholder frames')

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
            self.picam2.start()
            self.ready_event.set()
        else:
            placeholder = self._make_placeholder()
            self.ready_event.set()

        while not self.stop_event.is_set():
            loop_start = time.time()
            try:
                frame = self.picam2.capture_array('main') if HAS_CAMERA else placeholder
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
            except Exception as e:
                print(f'[CAM] frame loop error: {e}')
                time.sleep(0.1)
                continue

            target_period = 1.0 / max(5, self.framerate)
            elapsed = time.time() - loop_start
            time.sleep(max(0.0, target_period - elapsed))

        if HAS_CAMERA:
            self.picam2.stop()
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
        self.started = False

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
