#!/usr/bin/env python3
"""巡线传感器模块"""
import time
import threading

try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except ImportError:
    GPIO = None
    HAS_GPIO = False

class Infrared:
    def __init__(self, track_pins=[13,15,11,7]):
        self.track_pins = track_pins
        self.data = {'track': [False]*4, 'edge_alarm': False}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.enabled = False
        self.thread = None
        self.started = False
        
        if HAS_GPIO:
            try:
                GPIO.setmode(GPIO.BOARD)
                GPIO.setwarnings(False)
                for pin in track_pins:
                    GPIO.setup(pin, GPIO.IN)
                self.enabled = True
                print('[IR] 初始化完成')
            except Exception as e:
                print(f'[IR] 初始化失败: {e}')
    
    def _run(self):
        while not self.stop_event.is_set():
            if not self.enabled:
                time.sleep(1)
                continue
            try:
                track = [GPIO.input(p) for p in self.track_pins]
                edge = not all(track)
                
                with self.lock:
                    self.data = {'track': track, 'edge_alarm': edge}
            except Exception as e:
                print(f'[IR] 读取错误: {e}')
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
