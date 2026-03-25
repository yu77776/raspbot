#!/usr/bin/env python3
"""Line tracking sensor module (track only)."""
import threading
import time

try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except ImportError:
    GPIO = None
    HAS_GPIO = False


class Infrared:
    def __init__(self, track_pins=[13, 15, 11, 7]):
        self.track_pins = track_pins
        self.data = {'track': [1, 1, 1, 1]}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.started = False
        self.enabled = False

        if HAS_GPIO:
            try:
                GPIO.setmode(GPIO.BOARD)
                GPIO.setwarnings(False)
                for pin in self.track_pins:
                    GPIO.setup(pin, GPIO.IN)
                self.enabled = True
                print('[TRACK] init ok')
            except Exception as e:
                print(f'[TRACK] init fail: {e}')

    def _run(self):
        while not self.stop_event.is_set():
            if not self.enabled:
                time.sleep(0.5)
                continue
            try:
                track = [GPIO.input(p) for p in self.track_pins]
                with self.lock:
                    self.data = {'track': track}
            except Exception as e:
                print(f'[TRACK] read error: {e}')
            time.sleep(0.05)

    def start(self):
        if not self.enabled:
            return
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

    def get_data(self):
        with self.lock:
            return dict(self.data)
