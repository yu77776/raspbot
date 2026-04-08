#!/usr/bin/env python3
"""RTMP push module for SRS/App playback."""
import threading


class VideoSrsStream:
    def __init__(self, camera, rtmp_url='', bitrate=4_000_000):
        self.camera = camera
        self.rtmp_url = str(rtmp_url or '').strip()
        self.bitrate = int(bitrate)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.started = False
        self.enabled = bool(self.rtmp_url)

    def start(self):
        with self.lock:
            if self.started:
                return
            if not self.enabled:
                print('[SRS] disabled')
                return
            self.stop_event.clear()
            self.camera.start_rtmp_stream(self.rtmp_url, bitrate=self.bitrate)
            self.started = True

    def stop(self):
        with self.lock:
            self.stop_event.set()
            if not self.started:
                return
            self.camera.stop_rtmp_stream()
            self.started = False

    def get_url(self):
        with self.lock:
            return self.rtmp_url

    def is_enabled(self):
        with self.lock:
            return self.enabled
