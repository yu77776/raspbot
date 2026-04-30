"""Motion controller for baby tracking.

Control model:
- Inner loop: pixel error -> servo PD -> pan/tilt servo angles.
- Outer loop: servo pan offset -> body spin command, with IMU yaw-rate damping.
- Distance follow: when pan servo is near center, move forward/backward by distance.

The outer motor loop is gated by settings.ENABLE_MOTOR_CONTROL. When it is
False, the controller still tracks with servos but always outputs action=stop.
"""

import math
import os
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import numpy as np

from . import settings as cfg
from .tuning import JsonTuner


class MotionState(Enum):
    IDLE = auto()
    TRACK = auto()
    SCAN = auto()


class FollowState(Enum):
    HOLD = auto()
    FORWARD = auto()
    BACKWARD = auto()
    COOLDOWN = auto()


@dataclass
class MotionOutput:
    servo_x: float = 90.0
    servo_y: float = 90.0
    action: str = "stop"
    speed: int = 0
    left_speed: int = 0
    right_speed: int = 0
    state: MotionState = MotionState.IDLE


class PID:
    def __init__(self, kp, ki, kd, i_max, out_max):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.i_max = i_max
        self.out_max = out_max
        self.integral = 0.0
        self.last_error = 0.0

    def reset(self):
        self.integral = 0.0
        self.last_error = 0.0

    def update(self, error, dt):
        if dt <= 0:
            return 0.0
        self.integral = float(np.clip(self.integral + error * dt, -self.i_max, self.i_max))
        d = (error - self.last_error) / dt
        self.last_error = error
        out = self.kp * error + self.ki * self.integral + self.kd * d
        return float(np.clip(out, -self.out_max, self.out_max))


@dataclass
class MotionConfig:
    frame_w: int = cfg.FRAME_W
    frame_h: int = cfg.FRAME_H
    center_x: int = cfg.CENTER_X
    center_y: int = cfg.CENTER_Y

    servo_kp_x: float = cfg.SERVO_KP_X
    servo_ki_x: float = 0.0
    servo_kd_x: float = cfg.SERVO_KD_X
    servo_kp_y: float = cfg.SERVO_KP_Y
    servo_ki_y: float = 0.0
    servo_kd_y: float = cfg.SERVO_KD_Y
    servo_i_max: float = cfg.SERVO_I_MAX
    servo_out_max_x: float = cfg.SERVO_OUT_MAX_X
    servo_out_max_y: float = cfg.SERVO_OUT_MAX_Y
    servo_dead_zone: float = 0.3
    servo_dir_x: int = cfg.SERVO_DIR_X
    servo_dir_y: int = cfg.SERVO_DIR_Y

    enable_servo_y: bool = cfg.ENABLE_SERVO_Y
    servo_y_hold: float = cfg.SERVO_Y_HOLD_ANGLE

    enable_motor_control: bool = cfg.ENABLE_MOTOR_CONTROL
    body_kp: float = 1.8
    body_kd_imu: float = 0.3
    body_dead_zone: float = 5.0
    body_speed_min: int = 40
    body_speed_max: int = 100
    body_out_max: float = 100.0

    enable_distance_follow: bool = True
    follow_dist_near: float = 28.0
    follow_dist_far: float = 45.0
    follow_hysteresis: float = 2.0
    follow_speed_kp: float = 2.2
    follow_speed_min: int = 45
    follow_speed_max: int = 80
    follow_back_speed_max: int = 60
    follow_servo_center_deg: float = 12.0
    follow_min_action_sec: float = 0.20
    follow_max_action_sec: float = 0.65
    follow_cooldown_sec: float = 0.30

    obstacle_cm: float = 30.0

    scan_speed_deg_s: float = 15.0
    scan_range_min: float = 30.0
    scan_range_max: float = 150.0
    scan_timeout: float = 10.0

    debug: bool = False
    debug_interval: float = 0.5


def _box_center(box):
    return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0


def _extract_imu_yaw(env_raw: dict) -> Optional[float]:
    """Extract IMU yaw angle from env data."""
    if not isinstance(env_raw, dict):
        return None
    imu = env_raw.get("imu")
    if not isinstance(imu, dict):
        return None
    try:
        return float(imu["yaw"])
    except (KeyError, TypeError, ValueError):
        return None


class MotionController:
    """Continuous servo tracking with optional body/distance follow."""

    def __init__(self, config=None, tuning_path=None):
        self.cfg = config or MotionConfig()
        if tuning_path is None:
            tuning_path = os.getenv("RASPBOT_MOTION_TUNING", os.path.join(cfg.BASE_DIR, "motion_tuning.json"))
        self.tuner = JsonTuner(tuning_path, self.cfg) if tuning_path else None
        self.state = MotionState.IDLE

        self.pid_x = PID(
            self.cfg.servo_kp_x,
            self.cfg.servo_ki_x,
            self.cfg.servo_kd_x,
            self.cfg.servo_i_max,
            self.cfg.servo_out_max_x,
        )
        self.pid_y = PID(
            self.cfg.servo_kp_y,
            self.cfg.servo_ki_y,
            self.cfg.servo_kd_y,
            self.cfg.servo_i_max,
            self.cfg.servo_out_max_y,
        )

        self.servo_x = 90.0
        self.servo_y = self.cfg.servo_y_hold if not self.cfg.enable_servo_y else 90.0
        self._prev_yaw = None
        self._scan_dir = 1
        self._scan_start_t = 0.0
        self._was_locked = False
        self._follow_state = FollowState.HOLD
        self._follow_until = 0.0
        self._follow_started_at = 0.0
        self._last_debug_t = 0.0

    def reset(self):
        self.state = MotionState.IDLE
        self.pid_x.reset()
        self.pid_y.reset()
        self.servo_x = 90.0
        self.servo_y = self.cfg.servo_y_hold if not self.cfg.enable_servo_y else 90.0
        self._prev_yaw = None
        self._was_locked = False
        self._reset_follow()

    def update(self, track_result, env_raw: dict, dt: float) -> MotionOutput:
        from .baby_filter import TrackState

        self._reload_tuning()

        is_locked = track_result.state == TrackState.LOCKED
        re_locked = is_locked and not self._was_locked
        self._was_locked = is_locked

        imu_yaw = _extract_imu_yaw(env_raw)
        dist_cm = float(env_raw.get("dist_cm", 999.0) or 999.0) if isinstance(env_raw, dict) else 999.0

        if self.state == MotionState.IDLE:
            if is_locked:
                self.state = MotionState.TRACK
                self._on_enter_track(imu_yaw)
        elif self.state == MotionState.TRACK:
            if not is_locked:
                self._enter_scan()
        elif self.state == MotionState.SCAN:
            if is_locked:
                self.state = MotionState.TRACK
                self._on_enter_track(imu_yaw)

        if self.state == MotionState.TRACK:
            out = self._do_track(track_result, imu_yaw, dist_cm, dt, re_locked)
        elif self.state == MotionState.SCAN:
            out = self._do_scan(dt)
        else:
            out = MotionOutput(servo_x=self.servo_x, servo_y=self.servo_y)

        self._log_debug(out, imu_yaw)
        self._prev_yaw = imu_yaw
        return out

    def _on_enter_track(self, imu_yaw):
        self.pid_x.reset()
        self.pid_y.reset()
        self._prev_yaw = imu_yaw

    def _reload_tuning(self):
        if not self.tuner:
            return
        changed = self.tuner.maybe_apply(self.cfg)
        if not changed:
            return

        self._apply_pid_config()
        if any(name.startswith("follow_") or name == "enable_distance_follow" for name in changed):
            self._reset_follow()
        print(f"[TUNING] reloaded {os.path.basename(self.tuner.path)}: {', '.join(changed)}")

    def _apply_pid_config(self):
        self.pid_x.kp = self.cfg.servo_kp_x
        self.pid_x.ki = self.cfg.servo_ki_x
        self.pid_x.kd = self.cfg.servo_kd_x
        self.pid_x.i_max = self.cfg.servo_i_max
        self.pid_x.out_max = self.cfg.servo_out_max_x

        self.pid_y.kp = self.cfg.servo_kp_y
        self.pid_y.ki = self.cfg.servo_ki_y
        self.pid_y.kd = self.cfg.servo_kd_y
        self.pid_y.i_max = self.cfg.servo_i_max
        self.pid_y.out_max = self.cfg.servo_out_max_y

    def tuning_overlay(self) -> str:
        if not self.tuner:
            return "tuning:off"
        names = (
            "enable_motor_control",
            "servo_kp_x",
            "servo_kd_x",
            "body_kp",
            "body_kd_imu",
            "body_speed_max",
            "follow_dist_near",
            "follow_dist_far",
        )
        return self.tuner.summary(names, self.cfg)

    def _enter_scan(self):
        self.state = MotionState.SCAN
        self._scan_dir = 1 if self.servo_x <= 90 else -1
        self._scan_start_t = time.monotonic()

    def _do_track(self, track_result, imu_yaw, dist_cm, dt, re_locked):
        from .baby_filter import TrackState

        if track_result.state != TrackState.LOCKED or track_result.box is None:
            self._enter_scan()
            return self._do_scan(dt)

        c = self.cfg
        cx, cy = _box_center(track_result.box)
        err_x = c.servo_dir_x * (cx - c.center_x)
        err_y = c.servo_dir_y * (cy - c.center_y)

        if re_locked:
            self.pid_x.reset()
            self.pid_y.reset()
            self._prev_yaw = imu_yaw

        dx = self.pid_x.update(err_x, dt)
        if abs(dx) >= c.servo_dead_zone:
            self.servo_x = float(np.clip(self.servo_x + dx, 0.0, 180.0))

        if c.enable_servo_y:
            dy = self.pid_y.update(err_y, dt)
            if abs(dy) >= c.servo_dead_zone:
                self.servo_y = float(np.clip(self.servo_y + dy, 0.0, 180.0))

        if not c.enable_motor_control:
            self._reset_follow()
            return MotionOutput(servo_x=self.servo_x, servo_y=self.servo_y, state=MotionState.TRACK)

        # Convert servo offset back to physical body-turn direction.
        servo_dev = (self.servo_x - 90.0) * c.servo_dir_x
        if abs(servo_dev) < c.body_dead_zone:
            motor_out = 0.0
        else:
            effective_dev = servo_dev - math.copysign(c.body_dead_zone, servo_dev)
            motor_out = c.body_kp * effective_dev
            if imu_yaw is not None and self._prev_yaw is not None and dt > 0:
                yaw_delta = imu_yaw - self._prev_yaw
                if yaw_delta > 180:
                    yaw_delta -= 360
                elif yaw_delta < -180:
                    yaw_delta += 360
                yaw_rate = yaw_delta / dt
                motor_out -= c.body_kd_imu * yaw_rate
            motor_out = float(np.clip(motor_out, -c.body_out_max, c.body_out_max))

        obstacle = dist_cm < c.obstacle_cm
        need_spin = abs(motor_out) >= 2.0 and not obstacle
        servo_centered = abs(servo_dev) < c.follow_servo_center_deg

        follow_action = None
        follow_speed = 0
        if c.enable_distance_follow and servo_centered and not need_spin and dist_cm < 900:
            follow_action, follow_speed = self._distance_follow_action(dist_cm, obstacle)
        else:
            self._reset_follow()

        if follow_action:
            action = follow_action
            speed = follow_speed
            left_speed = right_speed = speed
        elif need_spin:
            speed = int(np.clip(abs(motor_out), c.body_speed_min, c.body_speed_max))
            action = "spin_right" if motor_out > 0 else "spin_left"
            left_speed = right_speed = speed
        else:
            action, speed = "stop", 0
            left_speed = right_speed = 0

        return MotionOutput(
            servo_x=self.servo_x,
            servo_y=self.servo_y,
            action=action,
            speed=speed,
            left_speed=left_speed,
            right_speed=right_speed,
            state=MotionState.TRACK,
        )

    def _do_scan(self, dt):
        c = self.cfg
        if time.monotonic() - self._scan_start_t > c.scan_timeout:
            return MotionOutput(servo_x=self.servo_x, servo_y=self.servo_y, state=MotionState.SCAN)

        step = c.scan_speed_deg_s * dt * self._scan_dir
        new_x = self.servo_x + step
        if new_x >= c.scan_range_max:
            new_x = c.scan_range_max
            self._scan_dir = -1
        elif new_x <= c.scan_range_min:
            new_x = c.scan_range_min
            self._scan_dir = 1
        self.servo_x = new_x

        return MotionOutput(servo_x=self.servo_x, servo_y=self.servo_y, state=MotionState.SCAN)

    def _reset_follow(self):
        self._follow_state = FollowState.HOLD
        self._follow_until = 0.0
        self._follow_started_at = 0.0

    def _distance_follow_action(self, dist_cm: float, obstacle: bool):
        c = self.cfg
        now = time.monotonic()

        if self._follow_state == FollowState.COOLDOWN:
            if now < self._follow_until:
                return None, 0
            self._follow_state = FollowState.HOLD

        if self._follow_state in (FollowState.FORWARD, FollowState.BACKWARD):
            action = "forward" if self._follow_state == FollowState.FORWARD else "backward"
            if action == "forward" and obstacle:
                self._follow_state = FollowState.COOLDOWN
                self._follow_until = now + c.follow_cooldown_sec
                return None, 0

            elapsed = now - self._follow_started_at
            reached_band = (
                (action == "forward" and dist_cm <= c.follow_dist_far)
                or (action == "backward" and dist_cm >= c.follow_dist_near)
            )
            if elapsed >= c.follow_min_action_sec and reached_band:
                self._follow_state = FollowState.COOLDOWN
                self._follow_until = now + c.follow_cooldown_sec
                return None, 0

            if now < self._follow_until:
                return action, self._follow_speed_for(action, dist_cm)

            self._follow_state = FollowState.COOLDOWN
            self._follow_until = now + c.follow_cooldown_sec
            return None, 0

        if dist_cm > c.follow_dist_far + c.follow_hysteresis and not obstacle:
            self._follow_state = FollowState.FORWARD
            self._follow_started_at = now
            self._follow_until = now + c.follow_max_action_sec
            return "forward", self._follow_speed_for("forward", dist_cm)

        if dist_cm < c.follow_dist_near - c.follow_hysteresis:
            self._follow_state = FollowState.BACKWARD
            self._follow_started_at = now
            self._follow_until = now + c.follow_max_action_sec
            return "backward", self._follow_speed_for("backward", dist_cm)

        return None, 0

    def _follow_speed_for(self, action: str, dist_cm: float) -> int:
        c = self.cfg
        if action == "forward":
            err = max(0.0, dist_cm - c.follow_dist_far)
            return int(np.clip(err * c.follow_speed_kp, c.follow_speed_min, c.follow_speed_max))

        err = max(0.0, c.follow_dist_near - dist_cm)
        return int(np.clip(err * c.follow_speed_kp, c.follow_speed_min, c.follow_back_speed_max))

    def _log_debug(self, out, imu_yaw):
        if not self.cfg.debug:
            return
        now = time.monotonic()
        if now - self._last_debug_t < self.cfg.debug_interval:
            return
        self._last_debug_t = now
        dev = self.servo_x - 90.0
        yaw = f"{imu_yaw:.1f}" if imu_yaw is not None else "-"
        print(
            f"[MOTION] {out.state.name} "
            f"servo=({out.servo_x:.1f},{out.servo_y:.1f}) dev={dev:+.1f} "
            f"act={out.action} spd={out.speed} yaw={yaw}"
        )
