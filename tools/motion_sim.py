"""
Raspbot motion control simulation — dual-loop PID + distance follow + state machine.

Usage:
    python tools/motion_sim.py
    python tools/motion_sim.py --speed 2.0   # faster
    python tools/motion_sim.py --no-motor     # servo only
"""

import argparse
import math
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.widgets import Button

matplotlib.use("TkAgg")


# ── PID ──────────────────────────────────────────────────────────
class PID:
    def __init__(self, kp, ki, kd):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.integral = 0.0
        self.last_error = 0.0

    def reset(self):
        self.integral = 0.0
        self.last_error = 0.0

    def update(self, error, dt):
        if dt <= 0:
            return 0.0
        self.integral += error * dt
        d = (error - self.last_error) / dt
        self.last_error = error
        return self.kp * error + self.ki * self.integral + self.kd * d


# ── Motion State Machine ─────────────────────────────────────────
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
class SimConfig:
    frame_w: int = 640
    frame_h: int = 480
    center_x: int = 320
    center_y: int = 240

    servo_kp_x: float = 0.02
    servo_kd_x: float = 0.002
    servo_dir_x: int = -1
    servo_dir_y: int = 1

    enable_motor_control: bool = True
    body_kp: float = 0.1
    body_kd_imu: float = 0.01
    body_dead_zone: float = 1.0
    body_speed_max: int = 50

    enable_distance_follow: bool = True
    follow_dist_near: float = 25.0
    follow_dist_far: float = 38.0
    follow_hysteresis: float = 1.0
    follow_speed_kp: float = 1.2
    follow_speed_min: int = 50
    follow_speed_max: int = 70
    follow_back_speed_max: int = 40
    follow_servo_center_deg: float = 20.0
    follow_cooldown_sec: float = 0.1
    follow_max_action_sec: float = 0.25
    follow_min_action_sec: float = 0.1
    obstacle_cm: float = 10.0

    scan_speed_deg_s: float = 20.0
    scan_range_min: float = 5.0
    scan_range_max: float = 175.0
    scan_timeout: float = 10.0


# ── Simulated Baby ──────────────────────────────────────────────
class BabySim:
    """A baby moving in a pattern across the frame."""

    def __init__(self, cfg: SimConfig):
        self.cfg = cfg
        self.x = float(cfg.center_x)
        self.y = float(cfg.center_y)
        self.visible = True
        self.t = 0.0
        self.pattern_timer = 0.0
        self._pattern = "circle"
        self._pattern_idx = 0
        self._patterns = ["circle", "zigzag", "hide", "approach", "retreat"]
        self._pattern_duration = 8.0

    def step(self, dt: float):
        self.t += dt
        self.pattern_timer += dt
        if self.pattern_timer > self._pattern_duration:
            self.pattern_timer = 0.0
            self._pattern_idx = (self._pattern_idx + 1) % len(self._patterns)
        pat = self._patterns[self._pattern_idx]

        c = self.cfg
        if pat == "circle":
            r = 160
            self.x = c.center_x + r * math.cos(self.t * 0.6)
            self.y = c.center_y + r * math.sin(self.t * 0.6)
            self.visible = True
        elif pat == "zigzag":
            phase = self.pattern_timer / self._pattern_duration
            self.x = 80 + 480 * phase
            self.y = c.center_y + 120 * math.sin(phase * 6 * math.pi)
            self.visible = True
        elif pat == "hide":
            if self.pattern_timer < 1.0:
                self.x += (500 - self.x) * dt * 2
                self.y += (120 - self.y) * dt * 2
                self.visible = True
            elif self.pattern_timer < 3.0:
                self.visible = False
            elif self.pattern_timer < 4.0:
                self.visible = True
                self.x += (c.center_x - self.x) * dt * 3
                self.y += (c.center_y - self.y) * dt * 3
            else:
                self.visible = True
        elif pat == "approach":
            d = c.frame_w * 0.5 * (self.pattern_timer / self._pattern_duration)
            self.x = c.center_x + d * math.cos(self.t * 0.3)
            self.y = c.center_y + d * math.sin(self.t * 0.3)
            self.visible = True
        elif pat == "retreat":
            d = c.frame_w * 0.5 * (1 - self.pattern_timer / self._pattern_duration)
            self.x = c.center_x + d * math.cos(self.t * 0.3)
            self.y = c.center_y + d * math.sin(self.t * 0.3)
            self.visible = True


# ── Motion Controller (simplified) ──────────────────────────────
class SimMotionController:
    def __init__(self, cfg: SimConfig):
        self.cfg = cfg
        self.state = MotionState.IDLE
        self.pid_x = PID(cfg.servo_kp_x, 0.0, cfg.servo_kd_x)
        self.servo_x = 90.0
        self.servo_y = 90.0
        self.car_x = 0.0
        self.car_y = 0.0
        self.car_heading = 0.0
        self.motor_out = 0.0
        self._scan_dir = 1
        self._scan_start_t = 0.0
        self._follow_state = FollowState.HOLD
        self._follow_until = 0.0
        self._follow_started_at = 0.0

    def update(self, baby: BabySim, dist_cm: float, dt: float):
        c = self.cfg
        now = time.monotonic()

        # State transitions
        if baby.visible and self.state != MotionState.SCAN:
            self.state = MotionState.TRACK
        elif not baby.visible and self.state == MotionState.TRACK:
            self.state = MotionState.SCAN
            self._scan_dir = 1 if self.servo_x <= 90 else -1
            self._scan_start_t = now

        if self.state == MotionState.IDLE:
            if baby.visible:
                self.state = MotionState.TRACK
        elif self.state == MotionState.SCAN:
            if baby.visible:
                self.state = MotionState.TRACK

        if self.state == MotionState.TRACK and baby.visible:
            # Inner loop: pixel → servo
            err_x = c.servo_dir_x * (baby.x - c.center_x)
            self.servo_x = float(np.clip(self.servo_x + self.pid_x.update(err_x, dt), 0.0, 180.0))

            # Outer loop: servo offset → body
            servo_dev = (self.servo_x - 90.0) * c.servo_dir_x
            if abs(servo_dev) >= c.body_dead_zone and c.enable_motor_control:
                effective = servo_dev - math.copysign(c.body_dead_zone, servo_dev)
                self.motor_out = float(np.clip(c.body_kp * effective, -50, 50))
            else:
                self.motor_out = 0.0

            # Apply heading + move car
            self.car_heading += self.motor_out * dt * 0.1
            self.car_heading %= 360

            # Distance follow
            servo_centered = abs(self.servo_x - 90.0) < c.follow_servo_center_deg
            if c.enable_distance_follow and servo_centered and abs(self.motor_out) < 2.0:
                self._do_distance_follow(dist_cm, now)

            if self._follow_until > now:
                follow_action = (
                    "forward" if self._follow_state in (FollowState.FORWARD,)
                    else "backward"
                )
                self._move_car(follow_action, dt, dist_cm)

        elif self.state == MotionState.SCAN:
            step = c.scan_speed_deg_s * dt * self._scan_dir
            self.servo_x += step
            if self.servo_x >= c.scan_range_max and self._scan_dir > 0:
                self._scan_dir = -1
            elif self.servo_x <= c.scan_range_min and self._scan_dir < 0:
                self._scan_dir = 1
            self.motor_out = 0.0
            if time.monotonic() - self._scan_start_t > c.scan_timeout:
                self.state = MotionState.IDLE

        else:
            self.motor_out = 0.0

    def _do_distance_follow(self, dist_cm: float, now: float):
        c = self.cfg
        if now < self._follow_until and self._follow_state == FollowState.COOLDOWN:
            return
        if dist_cm > c.follow_dist_far + c.follow_hysteresis:
            self._follow_state = FollowState.FORWARD
            self._follow_started_at = now
            self._follow_until = now + c.follow_max_action_sec
        elif dist_cm < c.follow_dist_near - c.follow_hysteresis:
            self._follow_state = FollowState.BACKWARD
            self._follow_started_at = now
            self._follow_until = now + c.follow_max_action_sec
        else:
            self._follow_state = FollowState.HOLD
            self._follow_until = 0.0

    def _move_car(self, action: str, dt: float, dist_cm: float):
        c = self.cfg
        if action == "forward":
            err = max(0.0, dist_cm - c.follow_dist_far)
            speed = np.clip(err * c.follow_speed_kp, c.follow_speed_min, c.follow_speed_max)
        else:
            err = max(0.0, c.follow_dist_near - dist_cm)
            speed = np.clip(err * c.follow_speed_kp, c.follow_speed_min, c.follow_back_speed_max)

        rad = math.radians(self.car_heading)
        step = float(speed) * dt * 0.02
        self.car_x += step * math.cos(rad)
        self.car_y += step * math.sin(rad)

    @property
    def servo_dev(self):
        return (self.servo_x - 90.0) * self.cfg.servo_dir_x


# ── Interactive Simulator ────────────────────────────────────────
class MotionSimulator:
    def __init__(self, cfg: SimConfig = None):
        self.cfg = cfg or SimConfig()
        self.baby = BabySim(self.cfg)
        self.ctrl = SimMotionController(self.cfg)
        self.dist_cm = 40.0  # simulated distance
        self.running = True
        self.paused = False
        self.dt_scale = 1.0

        # Recording
        self.history = {"cx": [], "cy": [], "sx": [], "sy": [], "car": [], "mr": []}

        self._setup_ui()

    def _setup_ui(self):
        self.fig = plt.figure("Raspbot Motion Simulator", figsize=(14, 7))
        self.fig.canvas.manager.set_window_title("Raspbot Motion Simulator")

        gs = self.fig.add_gridspec(2, 3, width_ratios=[3, 1.5, 1.5], hspace=0.35)

        # Main camera view
        self.ax_cam = self.fig.add_subplot(gs[0, 0])
        self.ax_cam.set_xlim(0, self.cfg.frame_w)
        self.ax_cam.set_ylim(self.cfg.frame_h, 0)
        self.ax_cam.set_title("Camera View (640×480)")
        self.ax_cam.set_facecolor("#1a1a2e")
        self.ax_cam.grid(True, alpha=0.15, color="white")

        # Draw center cross
        self.ax_cam.axhline(self.cfg.center_y, color="gray", alpha=0.3, ls="--", lw=0.5)
        self.ax_cam.axvline(self.cfg.center_x, color="gray", alpha=0.3, ls="--", lw=0.5)

        # Baby position dot
        (self.baby_dot,) = self.ax_cam.plot([], [], "ro", ms=12, alpha=0.9, label="Baby")
        (self.baby_trail,) = self.ax_cam.plot([], [], "r-", alpha=0.15, lw=0.8)
        self.baby_bbox = None

        # Servo crosshair
        (self.servo_xhair,) = self.ax_cam.plot([], [], "g+", ms=20, mew=2, label="Servo aim")
        (self.servo_history,) = self.ax_cam.plot([], [], "g-", alpha=0.2, lw=0.5)

        self.ax_cam.legend(loc="upper right", fontsize=8)

        # Top-down car view
        self.ax_top = self.fig.add_subplot(gs[0, 1])
        self.ax_top.set_xlim(-4, 4)
        self.ax_top.set_ylim(-4, 4)
        self.ax_top.set_aspect("equal")
        self.ax_top.set_title("Top-down (Car + Baby)")
        self.ax_top.set_facecolor("#0d1b2a")
        self.ax_top.grid(True, alpha=0.2, color="white")
        self.car_arrow = None
        (self.baby_top,) = self.ax_top.plot([], [], "ro", ms=8, alpha=0.8)

        # State info panel
        self.ax_info = self.fig.add_subplot(gs[0, 2])
        self.ax_info.set_xlim(0, 1)
        self.ax_info.set_ylim(0, 1)
        self.ax_info.axis("off")
        self.ax_info.set_title("State")
        self.info_texts = []
        self._draw_info_panel()

        # Servo angle gauge
        self.ax_servo = self.fig.add_subplot(gs[1, 0])
        self.ax_servo.set_xlim(0, 180)
        self.ax_servo.set_ylim(-1.5, 1.5)
        self.ax_servo.set_title("Pan Servo Angle (0°–180°)")
        self.ax_servo.set_yticks([])
        self.ax_servo.axhline(0, color="gray", alpha=0.3, lw=0.5)
        self.ax_servo.axvline(90, color="gray", alpha=0.5, ls="--", lw=0.5, label="center")
        self.servo_bar = None
        self.servo_zone_left = self.ax_servo.axvspan(0, 90 - self.cfg.follow_servo_center_deg, alpha=0.08, color="blue")
        self.servo_zone_right = self.ax_servo.axvspan(90 + self.cfg.follow_servo_center_deg, 180, alpha=0.08, color="blue")
        (self.servo_line,) = self.ax_servo.plot([90, 90], [-1, 1], "g-", lw=3, alpha=0.8)

        # Distance + PID error chart
        self.ax_dist = self.fig.add_subplot(gs[1, 1])
        self.ax_dist.set_title("Follow Distance (cm)")
        self.ax_dist.set_ylim(0, 80)
        self.ax_dist.set_xlabel("time")
        self.ax_dist.axhline(self.cfg.follow_dist_far, color="orange", ls="--", lw=0.8, label="far 38cm")
        self.ax_dist.axhline(self.cfg.follow_dist_near, color="cyan", ls="--", lw=0.8, label="near 25cm")
        self.ax_dist.legend(fontsize=7, loc="upper right")
        (self.dist_line,) = self.ax_dist.plot([], [], "b-", lw=1.5)
        self.dist_history_x = []
        self.dist_history_y = []

        # Motor output chart
        self.ax_motor = self.fig.add_subplot(gs[1, 2])
        self.ax_motor.set_title("Motor Output")
        self.ax_motor.set_ylim(-60, 60)
        self.ax_motor.set_xlabel("time")
        self.ax_motor.axhline(0, color="gray", alpha=0.3, lw=0.5)
        (self.motor_line,) = self.ax_motor.plot([], [], "r-", lw=1.5)
        self.motor_history_x = []
        self.motor_history_y = []

        self.fig.tight_layout()

        # Keyboard
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.fig.canvas.mpl_connect("close_event", lambda e: self.stop())

    def _draw_info_panel(self):
        for t in self.info_texts:
            t.remove() if hasattr(t, "remove") else None
        self.info_texts.clear()
        ctrl = self.ctrl
        bb = self.baby
        cfg = self.cfg

        lines = [
            f"State: {ctrl.state.name}",
            f"Baby: {'visible' if bb.visible else 'HIDDEN'}",
            f"Servo X: {ctrl.servo_x:.1f}°",
            f"Servo Dev: {ctrl.servo_dev:+.1f}°",
            f"Motor Out: {ctrl.motor_out:+.1f}",
            f"Distance: {self.dist_cm:.1f} cm",
            f"Follow: {ctrl._follow_state.name}",
            f"Car Heading: {ctrl.car_heading:.0f}°",
            f"",
            f"PID kp={cfg.servo_kp_x} kd={cfg.servo_kd_x}",
            f"Body kp={cfg.body_kp} kd_imu={cfg.body_kd_imu}",
            f"Near={cfg.follow_dist_near} Far={cfg.follow_dist_far}",
            f"Speed: {self.dt_scale:.1f}×",
        ]

        for i, line in enumerate(lines):
            color = "white" if line.startswith("State") or line.startswith("Baby") else "#aaa"
            t = self.ax_info.text(0.05, 0.95 - i * 0.065, line, transform=self.ax_info.transAxes,
                                  fontsize=9, color=color, fontfamily="monospace")
            self.info_texts.append(t)

    def _on_key(self, event):
        if event.key == " ":
            self.paused = not self.paused
        elif event.key == "up":
            self.dt_scale = min(5.0, self.dt_scale + 0.5)
        elif event.key == "down":
            self.dt_scale = max(0.1, self.dt_scale - 0.5)
        elif event.key == "q":
            self.stop()
        elif event.key == "left":
            self.dist_cm = max(5.0, self.dist_cm - 5)
        elif event.key == "right":
            self.dist_cm = min(100.0, self.dist_cm + 5)

    def stop(self):
        self.running = False
        plt.close("all")

    def run(self):
        last_frame = time.perf_counter()
        step = 0
        while self.running:
            now = time.perf_counter()
            if self.paused:
                self.fig.canvas.draw_idle()
                self.fig.canvas.flush_events()
                plt.pause(0.05)
                last_frame = now
                continue

            dt_raw = now - last_frame
            last_frame = now
            dt = min(dt_raw, 0.1) * self.dt_scale

            # Random distance variation
            self.dist_cm += (np.random.randn() * 2 - 0.5) * dt
            self.dist_cm = np.clip(self.dist_cm, 5, 80)

            self.baby.step(dt)
            self.ctrl.update(self.baby, self.dist_cm, dt)

            self._redraw(step)
            step += 1
            plt.pause(max(0.016, dt / self.dt_scale * 0.5))

    def _redraw(self, step):
        # Baby
        if self.baby.visible:
            bx, by = self.baby.x, self.baby.y
            self.history["cx"].append(bx)
            self.history["cy"].append(by)
            if len(self.history["cx"]) > 80:
                for k in self.history:
                    self.history[k] = self.history[k][-80:]
            self.baby_dot.set_data([bx], [by])
            self.baby_trail.set_data(self.history["cx"], self.history["cy"])
            if self.baby_bbox:
                self.baby_bbox.remove()
            w, h = 40, 50
            self.baby_bbox = patches.Rectangle((bx - w / 2, by - h / 2), w, h,
                                                facecolor="none", edgecolor="red", lw=1, alpha=0.6)
            self.ax_cam.add_patch(self.baby_bbox)
        else:
            self.baby_dot.set_data([], [])
            self.baby_trail.set_data([], [])
            if self.baby_bbox:
                self.baby_bbox.remove()
                self.baby_bbox = None

        # Servo
        sx, sy = self.ctrl.servo_x, self.ctrl.servo_y
        # map servo → pixel: servo=90 maps to center
        servo_px = self.cfg.center_x + (sx - 90) * 6
        servo_py = self.cfg.center_y
        self.history["sx"].append(servo_px)
        self.history["sy"].append(servo_py)
        if len(self.history["sx"]) > 80:
            self.history["sx"] = self.history["sx"][-80:]
            self.history["sy"] = self.history["sy"][-80:]
        self.servo_xhair.set_data([servo_px], [servo_py])
        self.servo_history.set_data(self.history["sx"], self.history["sy"])

        # Top-down
        rad = math.radians(self.ctrl.car_heading)
        cx, cy = self.ctrl.car_x, self.ctrl.car_y
        bx, by = cx + self.dist_cm * 0.04 * math.cos(rad), cy + self.dist_cm * 0.04 * math.sin(rad)
        self.baby_top.set_data([bx], [by])
        if self.car_arrow:
            self.car_arrow.remove()
        dx = 1.5 * math.cos(rad)
        dy = 1.5 * math.sin(rad)
        self.car_arrow = self.ax_top.arrow(cx, cy, dx, dy, head_width=0.3, head_length=0.3,
                                            fc="cyan", ec="cyan", alpha=0.9)
        self.ax_top.set_title(f"Top-down (dist={self.dist_cm:.0f}cm heading={self.ctrl.car_heading:.0f}°)")

        # Servo gauge
        self.servo_line.set_data([sx, sx], [-1, 1])
        color = "lime" if abs(sx - 90) < self.cfg.follow_servo_center_deg else "orange"
        self.servo_line.set_color(color)

        # Distance chart
        self.dist_history_x.append(step * 0.05)
        self.dist_history_y.append(self.dist_cm)
        if len(self.dist_history_x) > 200:
            self.dist_history_x = self.dist_history_x[-200:]
            self.dist_history_y = self.dist_history_y[-200:]
        self.dist_line.set_data(self.dist_history_x, self.dist_history_y)
        self.ax_dist.set_xlim(max(0, self.dist_history_x[0]), self.dist_history_x[-1] + 1)

        # Motor chart
        self.motor_history_x.append(step * 0.05)
        self.motor_history_y.append(self.ctrl.motor_out)
        if len(self.motor_history_x) > 200:
            self.motor_history_x = self.motor_history_x[-200:]
            self.motor_history_y = self.motor_history_y[-200:]
        self.motor_line.set_data(self.motor_history_x, self.motor_history_y)
        self.ax_motor.set_xlim(max(0, self.motor_history_x[0]), self.motor_history_x[-1] + 1)

        # Info panel
        self._draw_info_panel()

        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()


def main():
    ap = argparse.ArgumentParser(description="Raspbot Motion Simulator")
    ap.add_argument("--no-motor", action="store_true", help="Disable body motor (servo only)")
    ap.add_argument("--speed", type=float, default=1.0, help="Simulation speed multiplier")
    args = ap.parse_args()

    cfg = SimConfig()
    if args.no_motor:
        cfg.enable_motor_control = False
        cfg.enable_distance_follow = False

    sim = MotionSimulator(cfg)
    sim.dt_scale = args.speed

    print("=" * 60)
    print("  Raspbot Dual-Loop PID Motion Simulator")
    print("=" * 60)
    print()
    print("  Controls:")
    print("    SPACE      — pause / resume")
    print("    ↑ / ↓      — speed up / slow down")
    print("    ← / →      — decrease / increase distance")
    print("    Q          — quit")
    print()
    print("  Watching: camera view + top-down + servo gauge")
    print("            + distance chart + motor output chart")
    print()

    sim.run()


if __name__ == "__main__":
    main()
