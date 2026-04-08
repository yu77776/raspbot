#!/usr/bin/env python3
"""电机和舵机控制模块"""
import sys
import os
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'driver'))

try:
    from YB_Pcb_Car import YB_Pcb_Car
    HAS_CAR = True
except ImportError:
    HAS_CAR = False

class Motor:
    def __init__(self):
        self.car = YB_Pcb_Car() if HAS_CAR else None
        self.last_servo1 = 90
        self.last_servo2 = 90
        self.lock = threading.Lock()
        self.dead_band = 1
        print(f'[MOTOR] 初始化完成 (enabled={HAS_CAR})')
    
    def set_servo(self, servo_id, angle):
        if not HAS_CAR:
            return
        angle = int(max(0, min(180, angle)))
        with self.lock:
            if servo_id == 1:
                if abs(angle - self.last_servo1) >= self.dead_band:
                    self.car.Ctrl_Servo(1, angle)
                    self.last_servo1 = angle
            elif servo_id == 2:
                if abs(angle - self.last_servo2) >= self.dead_band:
                    self.car.Ctrl_Servo(2, angle)
                    self.last_servo2 = angle
    
    def forward(self, left, right):
        if HAS_CAR:
            self.car.Car_Run(left, right)
    
    def backward(self, speed):
        if HAS_CAR:
            self.car.Car_Back(speed, speed)

    def left(self, speed, inner_ratio=0.5):
        if HAS_CAR:
            s = int(max(0, min(255, speed)))
            inner = int(max(0, min(255, s * float(inner_ratio))))
            self.car.Car_Left(inner, s)

    def right(self, speed, inner_ratio=0.5):
        if HAS_CAR:
            s = int(max(0, min(255, speed)))
            inner = int(max(0, min(255, s * float(inner_ratio))))
            self.car.Car_Right(s, inner)
    
    def spin_left(self, speed):
        if HAS_CAR:
            self.car.Car_Spin_Left(speed, speed)
    
    def spin_right(self, speed):
        if HAS_CAR:
            self.car.Car_Spin_Right(speed, speed)
    
    def stop(self):
        if HAS_CAR:
            self.car.Car_Stop()

if __name__ == '__main__':
    print('Testing motor module...')
    motor = Motor()
    motor.set_servo(1, 90)
    print('Servo1 -> 90deg')
    import time
    time.sleep(1)
    motor.forward(100, 100)
    print('Forward 2s')
    time.sleep(2)
    motor.stop()
    print('Stop')
