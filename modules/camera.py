#!/usr/bin/env python3
"""摄像头采集模块"""
import time
import threading
import cv2
import numpy as np

try:
    from picamera2 import Picamera2
    HAS_CAMERA = True
except ImportError:
    HAS_CAMERA = False

class Camera:
    def __init__(self, width=640, height=480, quality=80):
        self.width = width
        self.height = height
        self.quality = quality
        self.latest_jpeg = b''
        self.frame_seq = 0
        self.fps = 0
        self.frame_count = 0
        self.fps_timer = time.time()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.picam2 = None
        self.thread = None
        self.started = False
        
        if HAS_CAMERA:
            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                main={'format': 'RGB888', 'size': (width, height)}
            )
            self.picam2.configure(config)
            print(f'[CAM] 初始化完成 {width}x{height}')
        else:
            print('[CAM] picamera2 不可用，使用占位帧')
    
    def _make_placeholder(self):
        img = np.zeros((self.height, self.width, 3), dtype='uint8')
        cv2.putText(img, 'NO CAMERA', (self.width//4, self.height//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,200,255), 3)
        return img
    
    def _run(self):
        if HAS_CAMERA:
            self.picam2.start()
        else:
            placeholder = self._make_placeholder()
        
        while not self.stop_event.is_set():
            frame = self.picam2.capture_array() if HAS_CAMERA else placeholder
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
            time.sleep(0.033)
        
        if HAS_CAMERA:
            self.picam2.stop()
    
    def start(self):
        if self.started and self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.started = True
    
    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
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
    import time
    for i in range(10):
        seq, jpeg = cam.get_frame()
        print(f'Frame {seq}: {len(jpeg)} bytes')
        time.sleep(0.5)
    cam.stop()
