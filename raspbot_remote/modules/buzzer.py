#!/usr/bin/env python3
"""Buzzer driver for cliff/suspension and general alarm signalling.

Uses PWM to drive both active and passive piezo buzzers.
"""

import os
import threading
import time

from logger_setup import setup_logger
from modules.base import ModuleBase

logger = setup_logger('raspbot.buzzer')

try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except ImportError:
    GPIO = None
    HAS_GPIO = False


class Buzzer(ModuleBase):
    join_timeout = 1.0

    def __init__(self, pin=None):
        if pin is None:
            pin = int(os.getenv('RASPBOT_BUZZER_PIN', '32'))
        self.pin = int(pin)
        self.pwm_freq = int(os.getenv('RASPBOT_BUZZER_FREQ', '2700'))
        self.pwm_duty = int(os.getenv('RASPBOT_BUZZER_DUTY', '50'))
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.started = False
        self.enabled = False
        self._pwm = None

        if HAS_GPIO:
            try:
                GPIO.setmode(GPIO.BOARD)
                GPIO.setup(self.pin, GPIO.OUT)
                self._pwm = GPIO.PWM(self.pin, self.pwm_freq)
                self._pwm.start(0)
                self.enabled = True
                logger.info('buzzer ready on BOARD pin %s (PWM %sHz)', self.pin, self.pwm_freq)
            except Exception as e:
                logger.warning('buzzer init failed (pin=%s); disabled: %s', self.pin, e)
        else:
            logger.warning('RPi.GPIO unavailable; buzzer disabled')

    def beep(self, duration_sec):
        if not self.enabled or self._pwm is None:
            return
        with self.lock:
            try:
                self._pwm.ChangeDutyCycle(self.pwm_duty)
                time.sleep(max(0.0, float(duration_sec)))
                self._pwm.ChangeDutyCycle(0)
            except Exception as e:
                logger.warning('buzzer beep error: %s', e)
                self._silence()

    def beep_pattern(self, times, on_sec, off_sec):
        if not self.enabled:
            return
        times = max(0, int(times))
        if times == 0:
            return
        threading.Thread(
            target=self._beep_pattern_sync,
            args=(times, on_sec, off_sec),
            daemon=True,
        ).start()

    def _can_start(self):
        return bool(self.enabled)

    def _run(self):
        while not self.stop_event.is_set():
            time.sleep(0.5)

    def _after_stop(self):
        self._silence()
        if self._pwm is not None:
            try:
                self._pwm.stop()
            except Exception:
                pass
            self._pwm = None
        if HAS_GPIO and self.enabled:
            try:
                GPIO.cleanup(self.pin)
            except Exception:
                pass

    def _beep_pattern_sync(self, times, on_sec, off_sec):
        for i in range(times):
            if self.stop_event.is_set():
                break
            self.beep(on_sec)
            if i < times - 1 and not self.stop_event.is_set():
                time.sleep(max(0.0, float(off_sec)))

    def _silence(self):
        if not self.enabled or self._pwm is None:
            return
        try:
            self._pwm.ChangeDutyCycle(0)
        except Exception:
            pass
