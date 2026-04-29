#!/usr/bin/env python3
"""Ultrasonic distance sensor module."""

import threading
import time

from modules.base import ModuleBase

try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except ImportError:
    GPIO = None
    HAS_GPIO = False


class Ultrasonic(ModuleBase):
    join_timeout = 1.0

    def __init__(self, trig_pin=16, echo_pin=18):
        self.trig = trig_pin
        self.echo = echo_pin
        self.distance = 999.0
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.enabled = False
        self.thread = None
        self.started = False

        if HAS_GPIO:
            try:
                GPIO.setmode(GPIO.BOARD)
                GPIO.setwarnings(False)
                GPIO.setup(self.echo, GPIO.IN)
                GPIO.setup(self.trig, GPIO.OUT)
                GPIO.output(self.trig, GPIO.LOW)
                self.enabled = True
                print('[USONIC] initialized')
            except Exception as e:
                print(f'[USONIC] init failed: {e}')

    def _measure_once(self):
        if not self.enabled:
            return -1
        try:
            GPIO.output(self.trig, GPIO.LOW)
            time.sleep(0.000002)
            GPIO.output(self.trig, GPIO.HIGH)
            time.sleep(0.000015)
            GPIO.output(self.trig, GPIO.LOW)

            t0 = time.time()
            while not GPIO.input(self.echo):
                if time.time() - t0 > 0.03:
                    return -1

            t1 = time.time()
            while GPIO.input(self.echo):
                if time.time() - t1 > 0.03:
                    return -1

            t2 = time.time()
            return ((t2 - t1) * 340 / 2) * 100
        except Exception:
            return -1

    def _run(self):
        buf = []
        while not self.stop_event.is_set():
            d = self._measure_once()
            if 0 < d < 500:
                buf.append(d)
                if len(buf) > 5:
                    buf.pop(0)
                median = sorted(buf)[len(buf) // 2]
                with self.lock:
                    self.distance = median
            time.sleep(0.1)

    def _can_start(self) -> bool:
        return bool(self.enabled)

    def get_distance(self):
        with self.lock:
            return self.distance


if __name__ == '__main__':
    print('Testing ultrasonic module...')
    us = Ultrasonic()
    us.start()
    for _ in range(10):
        print(f'Distance: {us.get_distance():.1f}cm')
        time.sleep(0.5)
    us.stop()
