#!/usr/bin/env python3
"""Camera capture module with optional RTMP H.264 streaming."""
import subprocess
import threading
import time

import cv2
import numpy as np

try:
    from picamera2 import Picamera2
    from picamera2.encoders import H264Encoder
    from picamera2.outputs import FileOutput
    HAS_CAMERA = True
except ImportError:
    Picamera2 = None
    H264Encoder = None
    FileOutput = None
    HAS_CAMERA = False


class Camera:
    def __init__(
        self,
        width=640,
        height=480,
        quality=80,
        stream_width=1280,
        stream_height=720,
        framerate=20,
    ):
        self.width = int(width)
        self.height = int(height)
        self.quality = int(quality)
        self.stream_width = int(stream_width)
        self.stream_height = int(stream_height)
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
        self.rtmp_url = ''
        self.rtmp_bitrate = 4_000_000
        self.rtmp_encoder = None
        self.rtmp_output = None
        self.rtmp_proc = None
        self.rtmp_started = False

        if HAS_CAMERA:
            self.picam2 = Picamera2()
            config = self.picam2.create_video_configuration(
                main={'format': 'YUV420', 'size': (self.stream_width, self.stream_height)},
                lores={'format': 'YUV420', 'size': (self.width, self.height)},
                controls={'FrameRate': self.framerate},
            )
            self.picam2.configure(config)
            print(
                f'[CAM] init ok lores={self.width}x{self.height} '
                f'main={self.stream_width}x{self.stream_height} fps={self.framerate}'
            )
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

    def _start_rtmp_locked(self):
        if not HAS_CAMERA or not self.picam2 or not self.rtmp_url or self.rtmp_started:
            return
        cmd = [
            'ffmpeg',
            '-loglevel', 'warning',
            '-re',
            '-fflags', 'nobuffer',
            '-f', 'h264',
            '-i', '-',
            '-an',
            '-c:v', 'copy',
            '-f', 'flv',
            self.rtmp_url,
        ]
        self.rtmp_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self.rtmp_encoder = H264Encoder(bitrate=self.rtmp_bitrate, repeat=True, framerate=self.framerate)
        self.rtmp_output = FileOutput(self.rtmp_proc.stdin)
        self.picam2.start_encoder(self.rtmp_encoder, self.rtmp_output, name='main')
        self.rtmp_started = True
        print(f'[SRS] RTMP streaming started: {self.rtmp_url}')

    def _stop_rtmp_locked(self):
        if not HAS_CAMERA or not self.picam2 or not self.rtmp_started:
            return
        try:
            self.picam2.stop_encoder(self.rtmp_encoder)
        except Exception as e:
            print(f'[SRS] stop encoder error: {e}')
        try:
            if self.rtmp_output:
                self.rtmp_output.stop()
        except Exception as e:
            print(f'[SRS] stop file output error: {e}')
        try:
            if self.rtmp_proc:
                self.rtmp_proc.terminate()
                self.rtmp_proc.wait(timeout=2.0)
        except Exception as e:
            print(f'[SRS] stop ffmpeg process error: {e}')
            try:
                if self.rtmp_proc:
                    self.rtmp_proc.kill()
            except Exception:
                pass
        self.rtmp_encoder = None
        self.rtmp_output = None
        self.rtmp_proc = None
        self.rtmp_started = False
        print('[SRS] RTMP streaming stopped')

    def _run(self):
        placeholder = None
        if HAS_CAMERA:
            self.picam2.start()
            self.ready_event.set()
            with self.lock:
                self._start_rtmp_locked()
        else:
            placeholder = self._make_placeholder()
            self.ready_event.set()

        while not self.stop_event.is_set():
            try:
                frame = self.picam2.capture_array('lores') if HAS_CAMERA else placeholder
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

            time.sleep(max(0.0, 1.0 / max(5, self.framerate)))

        if HAS_CAMERA:
            with self.lock:
                self._stop_rtmp_locked()
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

    def start_rtmp_stream(self, rtmp_url, bitrate=4_000_000):
        rtmp_url = str(rtmp_url or '').strip()
        if not rtmp_url:
            return
        with self.lock:
            self.rtmp_url = rtmp_url
            self.rtmp_bitrate = int(bitrate)
            if self.ready_event.is_set():
                self._start_rtmp_locked()

    def stop_rtmp_stream(self):
        with self.lock:
            self._stop_rtmp_locked()
            self.rtmp_url = ''

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
