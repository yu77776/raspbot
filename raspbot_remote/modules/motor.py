#!/usr/bin/env python3
"""Motor and servo control module."""

import os
import sys
import threading
import time
from typing import Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'driver'))

try:
    from YB_Pcb_Car import YB_Pcb_Car
    HAS_CAR = True
except ImportError:
    HAS_CAR = False


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return False


def _clamp_float(value, min_v, max_v):
    return max(float(min_v), min(float(max_v), float(value)))


def _wrap_angle_deg(angle):
    a = float(angle)
    while a > 180.0:
        a -= 360.0
    while a < -180.0:
        a += 360.0
    return a


class Motor:
    def __init__(self):
        self.car = YB_Pcb_Car() if HAS_CAR else None
        self.last_servo1 = 90
        self.last_servo2 = 90
        self.lock = threading.Lock()
        self.dead_band = 1
        self.closed_loop_enabled = _as_bool(os.getenv('RASPBOT_MOTION_CLOSED_LOOP', '1'))
        self.heading_kp = float(os.getenv('RASPBOT_HEADING_KP', '1.8'))
        self.heading_rate_kp = float(os.getenv('RASPBOT_HEADING_RATE_KP', '0.12'))
        self.heading_trim_max = int(max(0, min(120, int(os.getenv('RASPBOT_HEADING_TRIM_MAX', '45')))))
        self.spin_rate_gain = float(os.getenv('RASPBOT_SPIN_RATE_GAIN', '0.90'))
        self.spin_yaw_kp = float(os.getenv('RASPBOT_SPIN_YAW_KP', '0.35'))
        self.spin_rate_kp = float(os.getenv('RASPBOT_SPIN_RATE_KP', '0.20'))
        self.spin_trim_max = int(max(0, min(120, int(os.getenv('RASPBOT_SPIN_TRIM_MAX', '80')))))
        self.yaw_sign = -1.0 if str(os.getenv('RASPBOT_IMU_YAW_SIGN', '1')).strip() in {'-1', '-1.0'} else 1.0
        self._last_action = 'stop'
        self._heading_target_yaw: Optional[float] = None
        self._spin_target_yaw: Optional[float] = None
        self._spin_last_ts = time.monotonic()
        print(f'[MOTOR] init done (enabled={HAS_CAR})')

    def _reset_motion_targets(self):
        self._heading_target_yaw = None
        self._spin_target_yaw = None

    def _read_imu_motion(self, env_packet) -> Optional[Tuple[float, float]]:
        if not self.closed_loop_enabled or env_packet is None:
            return None
        imu_payload = getattr(env_packet, 'imu', None)
        if not imu_payload or not getattr(imu_payload, 'healthy', False) or not getattr(imu_payload, 'calibrated', False):
            return None
        yaw = _wrap_angle_deg(float(getattr(imu_payload, 'yaw', 0.0)) * self.yaw_sign)
        yaw_rate = float(getattr(imu_payload, 'yaw_rate', 0.0)) * self.yaw_sign
        return yaw, yaw_rate

    def _mark_action(self, action):
        if action not in {'forward', 'backward'}:
            self._heading_target_yaw = None
        if action not in {'spin_left', 'spin_right'}:
            self._spin_target_yaw = None
            self._spin_last_ts = time.monotonic()
        self._last_action = action

    def _write_servo(self, servo_id, angle):
        if not HAS_CAR:
            return
        self.car.Ctrl_Servo(int(servo_id), int(angle))
        if servo_id == 1:
            self.last_servo1 = int(angle)
        elif servo_id == 2:
            self.last_servo2 = int(angle)

    def set_servo(self, servo_id, angle):
        if not HAS_CAR:
            return
        angle = int(max(0, min(180, angle)))
        with self.lock:
            if servo_id == 1:
                if abs(angle - self.last_servo1) >= self.dead_band:
                    self._write_servo(1, angle)
            elif servo_id == 2:
                if abs(angle - self.last_servo2) >= self.dead_band:
                    self._write_servo(2, angle)

    def center_servos(self, angle1=90, angle2=90, force=True):
        """Center both servos. force=True bypasses dead-band filtering."""
        a1 = int(max(0, min(180, angle1)))
        a2 = int(max(0, min(180, angle2)))
        with self.lock:
            if force:
                self._write_servo(1, a1)
                self._write_servo(2, a2)
            else:
                if abs(a1 - self.last_servo1) >= self.dead_band:
                    self._write_servo(1, a1)
                if abs(a2 - self.last_servo2) >= self.dead_band:
                    self._write_servo(2, a2)

    def forward(self, left, right, env_packet=None):
        imu_motion = self._read_imu_motion(env_packet)
        if imu_motion is None:
            if HAS_CAR:
                self.car.Car_Run(left, right)
            self._mark_action('forward')
            return

        yaw, yaw_rate = imu_motion
        if self._last_action != 'forward' or self._heading_target_yaw is None:
            self._heading_target_yaw = yaw
        yaw_err = _wrap_angle_deg(self._heading_target_yaw - yaw)
        corr = self.heading_kp * yaw_err - self.heading_rate_kp * yaw_rate
        corr = _clamp_float(corr, -self.heading_trim_max, self.heading_trim_max)
        self.drive_tank(left - corr, right + corr)
        self._mark_action('forward')

    def drive_tank(self, left_speed, right_speed):
        """Drive left/right wheels with signed speeds in [-255, 255]."""
        if HAS_CAR:
            l = int(max(-255, min(255, int(left_speed))))
            r = int(max(-255, min(255, int(right_speed))))
            self.car.Control_Car(l, r)

    def backward(self, speed, left_speed=None, right_speed=None, env_packet=None):
        left = int(speed if left_speed is None else left_speed)
        right = int(speed if right_speed is None else right_speed)
        imu_motion = self._read_imu_motion(env_packet)
        if imu_motion is None:
            if HAS_CAR:
                self.car.Car_Back(left, right)
            self._mark_action('backward')
            return

        yaw, yaw_rate = imu_motion
        if self._last_action != 'backward' or self._heading_target_yaw is None:
            self._heading_target_yaw = yaw
        yaw_err = _wrap_angle_deg(self._heading_target_yaw - yaw)
        corr = self.heading_kp * yaw_err - self.heading_rate_kp * yaw_rate
        corr = _clamp_float(corr, -self.heading_trim_max, self.heading_trim_max)
        self.drive_tank(-left - corr, -right + corr)
        self._mark_action('backward')

    def left(self, speed, inner_ratio=0.5):
        if HAS_CAR:
            s = int(max(0, min(255, speed)))
            inner = int(max(0, min(255, s * float(inner_ratio))))
            self.car.Car_Left(inner, s)
        self._mark_action('left')

    def right(self, speed, inner_ratio=0.5):
        if HAS_CAR:
            s = int(max(0, min(255, speed)))
            inner = int(max(0, min(255, s * float(inner_ratio))))
            self.car.Car_Right(s, inner)
        self._mark_action('right')

    def spin_left(self, speed, env_packet=None):
        imu_motion = self._read_imu_motion(env_packet)
        if imu_motion is None:
            if HAS_CAR:
                self.car.Car_Spin_Left(speed, speed)
            self._mark_action('spin_left')
            return

        yaw, yaw_rate = imu_motion
        now = time.monotonic()
        dt = _clamp_float(now - self._spin_last_ts, 0.01, 0.2)
        self._spin_last_ts = now
        if self._last_action != 'spin_left' or self._spin_target_yaw is None:
            self._spin_target_yaw = yaw
        desired_rate = max(0.0, float(speed) * self.spin_rate_gain)
        self._spin_target_yaw = _wrap_angle_deg(self._spin_target_yaw + desired_rate * dt)
        yaw_err = _wrap_angle_deg(self._spin_target_yaw - yaw)
        rate_err = desired_rate - yaw_rate
        corr = self.spin_yaw_kp * yaw_err + self.spin_rate_kp * rate_err
        corr = _clamp_float(corr, -self.spin_trim_max, self.spin_trim_max)
        self.drive_tank(-speed - corr, speed + corr)
        self._mark_action('spin_left')

    def spin_right(self, speed, env_packet=None):
        imu_motion = self._read_imu_motion(env_packet)
        if imu_motion is None:
            if HAS_CAR:
                self.car.Car_Spin_Right(speed, speed)
            self._mark_action('spin_right')
            return

        yaw, yaw_rate = imu_motion
        now = time.monotonic()
        dt = _clamp_float(now - self._spin_last_ts, 0.01, 0.2)
        self._spin_last_ts = now
        if self._last_action != 'spin_right' or self._spin_target_yaw is None:
            self._spin_target_yaw = yaw
        desired_rate = max(0.0, float(speed) * self.spin_rate_gain)
        self._spin_target_yaw = _wrap_angle_deg(self._spin_target_yaw - desired_rate * dt)
        yaw_err = _wrap_angle_deg(self._spin_target_yaw - yaw)
        rate_err = -desired_rate - yaw_rate
        corr = self.spin_yaw_kp * yaw_err + self.spin_rate_kp * rate_err
        corr = _clamp_float(corr, -self.spin_trim_max, self.spin_trim_max)
        self.drive_tank(speed - corr, -speed + corr)
        self._mark_action('spin_right')

    def stop(self):
        if HAS_CAR:
            self.car.Car_Stop()
        self._reset_motion_targets()
        self._last_action = 'stop'

    def execute_motion(self, action, speed, left_speed=None, right_speed=None, env_packet=None):
        action = str(action or 'stop')
        speed = int(max(0, min(255, int(speed))))
        left = int(max(0, min(255, int(speed if left_speed is None else left_speed))))
        right = int(max(0, min(255, int(speed if right_speed is None else right_speed))))

        if action == 'forward':
            self.forward(left, right, env_packet=env_packet)
        elif action == 'backward':
            self.backward(speed, left_speed=left, right_speed=right, env_packet=env_packet)
        elif action == 'spin_left':
            self.spin_left(speed, env_packet=env_packet)
        elif action == 'spin_right':
            self.spin_right(speed, env_packet=env_packet)
        elif action == 'left':
            self.left(speed)
        elif action == 'right':
            self.right(speed)
        else:
            self.stop()


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
