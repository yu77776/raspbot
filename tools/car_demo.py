"""
Raspbot 小车双环伺服跟踪演示 — 可视化小车模型 + 舵机旋转 + 车身跟随
基于 raspbot1/pc_modules/motion_controller.py 真实控制逻辑

Usage:
    python tools/car_demo.py
    python tools/car_demo.py --speed 2.0
    python tools/car_demo.py --no-motor   # 仅舵机，车身不转

Controls:
    SPACE    — 暂停/继续
    ↑ / ↓    — 加速/减速
    ← / →    — 减小/增大距离
    1/2/3    — 切换宝宝运动模式 (绕圈/折线/躲藏)
    Q        — 退出
    鼠标点击  — 把宝宝移到点击位置
"""

import argparse
import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.transforms import Affine2D

# 设置中文字体 (Windows)
_matplotlib_font = None
for _font_name in ["Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC"]:
    try:
        matplotlib.font_manager.findfont(_font_name, fallback_to_default=False)
        _matplotlib_font = _font_name
        break
    except Exception:
        continue
if _matplotlib_font:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [_matplotlib_font, "DejaVu Sans"]
else:
    plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["axes.unicode_minus"] = False

# ═══════════════════════════════════════════════════════════════════
# PID — 直接来自 motion_controller.py
# ═══════════════════════════════════════════════════════════════════


class PID:
    def __init__(self, kp=0.0, ki=0.0, kd=0.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral = 0.0
        self.last_error = 0.0

    def reset(self):
        self.integral = 0.0
        self.last_error = 0.0

    def update(self, error: float, dt: float) -> float:
        if dt <= 0:
            return 0.0
        self.integral += error * dt
        d = (error - self.last_error) / dt
        self.last_error = error
        return self.kp * error + self.ki * self.integral + self.kd * d


# ═══════════════════════════════════════════════════════════════════
# 状态机 — 直接来自 motion_controller.py
# ═══════════════════════════════════════════════════════════════════


class MotionState(Enum):
    IDLE = auto()
    TRACK = auto()
    SCAN = auto()


class FollowState(Enum):
    HOLD = auto()
    FORWARD = auto()
    BACKWARD = auto()
    COOLDOWN = auto()


# ═══════════════════════════════════════════════════════════════════
# 配置 — 数值来自 motion_tuning.json
# ═══════════════════════════════════════════════════════════════════


@dataclass
class DemoConfig:
    # 摄像头 / 画面
    frame_w: int = 640
    frame_h: int = 480
    center_x: int = 320
    center_y: int = 240
    camera_fov_deg: float = 62.0  # 摄像头水平视场角

    # 舵机 PD (Kp/Kd 来自 motion_tuning.json)
    servo_kp_x: float = 0.02
    servo_kd_x: float = 0.002
    # 仿真用 servo_dir_x=+1; 真实小车因摄像头倒装用-1
    servo_dir_x: int = 1

    # 车身控制 (来自 motion_tuning.json)
    enable_motor_control: bool = True
    body_kp: float = 0.1
    body_kd_imu: float = 0.01
    body_dead_zone: float = 1.0
    body_speed_min: float = 40.0
    body_speed_max: float = 50.0  # deg/s 级

    # 距离跟随 (来自 motion_tuning.json)
    enable_distance_follow: bool = True
    follow_dist_near: float = 25.0  # cm
    follow_dist_far: float = 38.0  # cm
    follow_hysteresis: float = 1.0
    follow_speed_kp: float = 1.2
    follow_speed_min: float = 50.0
    follow_speed_max: float = 70.0
    follow_back_speed_max: float = 40.0
    follow_servo_center_deg: float = 20.0
    follow_cooldown_sec: float = 0.1
    follow_max_action_sec: float = 0.25
    follow_min_action_sec: float = 0.1
    obstacle_cm: float = 10.0

    # 扫描 (来自 motion_tuning.json)
    scan_speed_deg_s: float = 20.0
    scan_range_min: float = 5.0
    scan_range_max: float = 175.0
    scan_timeout: float = 10.0

    # 世界坐标
    world_size: float = 10.0  # 场景尺寸 (米)
    pixels_per_deg: float = 0.0  # 由 FOV 和 frame_w 计算

    def __post_init__(self):
        self.pixels_per_deg = self.frame_w / self.camera_fov_deg


# ═══════════════════════════════════════════════════════════════════
# 宝宝模拟 — 在世界中移动
# ═══════════════════════════════════════════════════════════════════


class BabySim:
    """模拟宝宝 — 默认鼠标手动控制，可按 1/2/3 切换自动模式。"""

    def __init__(self, world_size: float = 10.0):
        self.world_size = world_size
        # 初始位置在场景中间偏右 (车的前方)
        self.x = world_size / 2 + 2.5
        self.y = world_size / 2
        self.visible = True
        self.t = 0.0
        self._mode = "manual"  # 默认手动 (鼠标控制)
        self._mode_timer = 0.0
        self._mode_duration = 8.0
        self._circle_radius = 2.5
        self._circle_speed = 0.3

    def switch_mode(self, mode: str):
        self._mode = mode
        self._mode_timer = 0.0

    def step(self, dt: float):
        self.t += dt
        self._mode_timer += dt

        if self._mode == "manual":
            # 手动模式: 不动, 等待鼠标拖拽
            return

        if self._mode_timer > self._mode_duration:
            self._mode_timer = 0.0
            modes = ["circle", "zigzag", "hide"]
            idx = modes.index(self._mode)
            self._mode = modes[(idx + 1) % len(modes)]

        cx, cy = self.world_size / 2, self.world_size / 2

        if self._mode == "circle":
            r = self._circle_radius
            angle = self.t * self._circle_speed
            self.x = cx + r * math.cos(angle)
            self.y = cy + r * math.sin(angle)
            self.visible = True

        elif self._mode == "zigzag":
            phase = self._mode_timer / self._mode_duration
            self.x = cx - 4 + 8 * phase
            self.y = cy + 2.5 * math.sin(phase * 6 * math.pi)
            self.visible = True

        elif self._mode == "hide":
            if self._mode_timer < 1.0:
                # 跑开
                self.x += (cx + 4 - self.x) * dt * 2
                self.y += (cy - 2 - self.y) * dt * 2
                self.visible = True
            elif self._mode_timer < 3.0:
                self.visible = False  # 躲起来
            elif self._mode_timer < 4.0:
                self.visible = True
                self.x += (cx - self.x) * dt * 3
                self.y += (cy - self.y) * dt * 3
            else:
                self.visible = True

    def world_pos(self) -> Tuple[float, float]:
        return self.x, self.y


# ═══════════════════════════════════════════════════════════════════
# 运动控制器 — 核心逻辑来自 motion_controller.py
# ═══════════════════════════════════════════════════════════════════


class CarController:
    """双环伺服跟踪 + 距离跟随。

    内环: 像素误差 → PD → 舵机角度
    外环: 舵机偏移 → 车身旋转 (带死区 + IMU阻尼)
    距离跟随: 舵机居中时前进/后退
    """

    def __init__(self, cfg: DemoConfig):
        self.cfg = cfg
        self.state = MotionState.IDLE

        # 舵机角度
        self.servo_x = 90.0  # 0-180, 90=正中
        self.servo_y = 90.0

        # PID 控制器
        self.pid_x = PID(cfg.servo_kp_x, 0.0, cfg.servo_kd_x)

        # 车身
        self.car_x = cfg.world_size / 2  # 世界坐标
        self.car_y = cfg.world_size / 2
        self.car_heading = 0.0  # 度, 0=右, 90=上
        self.motor_out = 0.0

        # IMU 阻尼用
        self._prev_heading = 0.0

        # 扫描
        self._scan_dir = 1
        self._scan_start_t = 0.0

        # 距离跟随
        self._follow_state = FollowState.HOLD
        self._follow_until = 0.0
        self._follow_started_at = 0.0

    def update(self, baby: BabySim, dist_cm: float, dt: float, sim_time: float):
        """主更新 — 与 MotionController.update() 结构一致。"""
        c = self.cfg
        # 有效可见性：宝宝全局可见 且 在摄像头 FOV 内
        pixel_pos = self._world_to_pixel(baby)
        baby_detected = pixel_pos is not None

        # ── 状态转移 ──
        if self.state == MotionState.IDLE:
            if baby_detected:
                self.state = MotionState.TRACK
                self.pid_x.reset()
            elif baby.visible:
                # 宝宝可见但不在 FOV 内 → 主动扫描寻找
                self._enter_scan(sim_time)
        elif self.state == MotionState.TRACK:
            if not baby_detected:
                self._enter_scan(sim_time)
        elif self.state == MotionState.SCAN:
            if baby_detected:
                self.state = MotionState.TRACK
                self.pid_x.reset()

        # ── 执行 ──
        if self.state == MotionState.TRACK and baby_detected:
            self._do_track(pixel_pos, dist_cm, dt, sim_time)
        elif self.state == MotionState.SCAN:
            self._do_scan(dt, sim_time)
        # IDLE: 不动

    def _world_to_pixel(self, baby: BabySim) -> Optional[Tuple[float, float]]:
        """将宝宝世界坐标转换为摄像头像素坐标。

        只有当宝宝在摄像头 FOV 内时才返回像素坐标，否则返回 None
        (模拟真实 YOLO 检测器的视野限制)。
        """
        if not baby.visible:
            return None

        # 宝宝相对于车的方位
        dx = baby.x - self.car_x
        dy = baby.y - self.car_y
        bearing = math.degrees(math.atan2(dy, dx))  # 宝宝在世界中的方位角

        # 摄像头绝对朝向: 车头 + 舵机偏移 (考虑了 servo_dir_x 的方向)
        servo_rel = (self.servo_x - 90.0) * self.cfg.servo_dir_x
        camera_heading = self.car_heading + servo_rel

        # 宝宝在摄像头视野中的角度误差
        angular_error = bearing - camera_heading
        # 归一化到 [-180, 180]
        while angular_error > 180:
            angular_error -= 360
        while angular_error < -180:
            angular_error += 360

        # FOV 检查: 超出摄像头视野的宝宝无法被检测到
        half_fov = self.cfg.camera_fov_deg / 2
        if abs(angular_error) > half_fov:
            return None  # 宝宝在视野外，模拟 YOLO 检测不到

        # 映射到像素坐标
        px = self.cfg.center_x + angular_error * self.cfg.pixels_per_deg
        # Y 轴简化：根据距离给一个大致的位置
        py = self.cfg.center_y + (dy - 2.0) * 20  # 粗略映射

        return px, py

    def _do_track(self, pixel_pos, dist_cm, dt, sim_time):
        """跟踪模式 — 直接对应 MotionController._do_track()。"""
        c = self.cfg
        if pixel_pos is None:
            self._enter_scan(sim_time)
            return

        cx, cy = pixel_pos

        # ── 内环: 像素误差 → PD → 舵机角度 ──
        err_x = c.servo_dir_x * (cx - c.center_x)
        dx = self.pid_x.update(err_x, dt)
        self.servo_x = float(np.clip(self.servo_x + dx, 0.0, 180.0))

        # ── 外环: 舵机偏移 → 车身旋转 ──
        servo_dev = self._servo_body_dev()
        if abs(servo_dev) >= c.body_dead_zone:
            effective = servo_dev - math.copysign(c.body_dead_zone, servo_dev)
            raw_out = c.body_kp * effective

            # IMU 阻尼 (用 heading 变化率模拟 yaw rate)
            heading_delta = self.car_heading - self._prev_heading
            if heading_delta > 180:
                heading_delta -= 360
            elif heading_delta < -180:
                heading_delta += 360
            yaw_rate = heading_delta / dt if dt > 0 else 0
            self.motor_out = float(np.clip(raw_out - c.body_kd_imu * yaw_rate, -100, 100))
        else:
            self.motor_out = 0.0

        # 应用车身旋转
        if c.enable_motor_control:
            # motor_out 正值 → heading 增加 (车头右转/CCW)
            # 缩放因子模拟实际电机驱动力矩 → 角速度的转换
            self.car_heading += self.motor_out * dt * 3.0
            self.car_heading %= 360

        self._prev_heading = self.car_heading

        # ── 距离跟随 ──
        servo_centered = abs(servo_dev) < c.follow_servo_center_deg
        if c.enable_distance_follow and servo_centered and abs(self.motor_out) < 2.0:
            self._distance_follow(dist_cm, sim_time)

        # 执行距离跟随动作 (移动车身)
        if self._follow_until > sim_time and c.enable_motor_control:
            self._move_car(dist_cm, dt)

    def _servo_body_dev(self) -> float:
        """舵机偏移量 (带方向)。"""
        return (self.servo_x - 90.0) * self.cfg.servo_dir_x

    def _enter_scan(self, sim_time: float):
        self.state = MotionState.SCAN
        self._scan_dir = 1 if self.servo_x <= 90 else -1
        self._scan_start_t = sim_time

    def _do_scan(self, dt: float, sim_time: float):
        """扫描模式 — 舵机来回扫。"""
        c = self.cfg
        if sim_time - self._scan_start_t > c.scan_timeout:
            self.state = MotionState.IDLE
            return

        step = c.scan_speed_deg_s * dt * self._scan_dir
        new_x = self.servo_x + step
        if new_x >= c.scan_range_max:
            new_x = c.scan_range_max
            self._scan_dir = -1
        elif new_x <= c.scan_range_min:
            new_x = c.scan_range_min
            self._scan_dir = 1
        self.servo_x = new_x
        self.motor_out = 0.0

    def _distance_follow(self, dist_cm: float, sim_time: float):
        """距离跟随状态机 — 直接对应 MotionController._distance_follow_action()。"""
        c = self.cfg

        if self._follow_state == FollowState.COOLDOWN:
            if sim_time < self._follow_until:
                return
            self._follow_state = FollowState.HOLD

        if self._follow_state in (FollowState.FORWARD, FollowState.BACKWARD):
            action = "forward" if self._follow_state == FollowState.FORWARD else "backward"
            reached = (
                (action == "forward" and dist_cm <= c.follow_dist_far)
                or (action == "backward" and dist_cm >= c.follow_dist_near)
            )
            elapsed = sim_time - self._follow_started_at
            if elapsed >= c.follow_min_action_sec and reached:
                self._follow_state = FollowState.COOLDOWN
                self._follow_until = sim_time + c.follow_cooldown_sec
                return
            if sim_time < self._follow_until:
                return
            self._follow_state = FollowState.COOLDOWN
            self._follow_until = sim_time + c.follow_cooldown_sec
            return

        if dist_cm > c.follow_dist_far + c.follow_hysteresis:
            self._follow_state = FollowState.FORWARD
            self._follow_started_at = sim_time
            self._follow_until = sim_time + c.follow_max_action_sec
        elif dist_cm < c.follow_dist_near - c.follow_hysteresis:
            self._follow_state = FollowState.BACKWARD
            self._follow_started_at = sim_time
            self._follow_until = sim_time + c.follow_max_action_sec

    def _move_car(self, dist_cm: float, dt: float):
        """根据距离跟随状态移动车身。"""
        c = self.cfg
        if self._follow_state == FollowState.FORWARD:
            err = max(0.0, dist_cm - c.follow_dist_far)
            speed = np.clip(err * c.follow_speed_kp, c.follow_speed_min, c.follow_speed_max)
            step = speed * dt * 0.005  # 缩放到世界坐标
        elif self._follow_state == FollowState.BACKWARD:
            err = max(0.0, c.follow_dist_near - dist_cm)
            speed = np.clip(err * c.follow_speed_kp, c.follow_speed_min, c.follow_back_speed_max)
            step = -speed * dt * 0.005
        else:
            return

        rad = math.radians(self.car_heading)
        self.car_x += step * math.cos(rad)
        self.car_y += step * math.sin(rad)

    def reset_follow(self):
        self._follow_state = FollowState.HOLD
        self._follow_until = 0.0
        self._follow_started_at = 0.0


# ═══════════════════════════════════════════════════════════════════
# 可视化 — 小车模型 + 舵机 + 场景
# ═══════════════════════════════════════════════════════════════════

# 颜色方案
COLOR_CAR_BODY = "#3a86ff"  # 蓝色车身
COLOR_CAR_ROOF = "#2660c4"  # 深蓝车顶
COLOR_WHEEL = "#1a1a1a"
COLOR_SERVO_BASE = "#adb5bd"  # 灰色舵机底座
COLOR_CAMERA = "#ff006e"  # 红色摄像头
COLOR_CAMERA_FOV = "#ff006e22"  # 半透明 FOV
COLOR_BABY = "#ffbe0b"  # 黄色宝宝
COLOR_BABY_HIDDEN = "#555555"
COLOR_TRAIL_CAR = "#3a86ff44"
COLOR_TRAIL_BABY = "#ffbe0b44"
COLOR_GRID = "#e0e0e0"
COLOR_BG = "#f8f9fa"


class CarDemo:
    """小车双环伺服跟踪可视化演示。"""

    def __init__(self, cfg: DemoConfig = None):
        self.cfg = cfg or DemoConfig()
        self.baby = BabySim(self.cfg.world_size)
        self.ctrl = CarController(self.cfg)
        self.dist_cm = 40.0  # 模拟距离 (cm)
        self.sim_time = 0.0

        self.running = True
        self.paused = False
        self.dt_scale = 1.0
        self.show_fov = True
        self._dragging = False  # 鼠标拖拽宝宝

        # 轨迹
        self._trail_car_x = []
        self._trail_car_y = []
        self._trail_baby_x = []
        self._trail_baby_y = []
        self._max_trail = 150

        self._setup_ui()

    # ── UI 搭建 ──

    def _setup_ui(self):
        self.fig = plt.figure("Raspbot — 小车双环伺服跟踪演示", figsize=(12, 9))
        self.fig.canvas.manager.set_window_title("Raspbot 小车演示")
        self.fig.patch.set_facecolor("#1a1a2e")

        gs = self.fig.add_gridspec(1, 2, width_ratios=[3.5, 1])

        # 主视图: 俯视场景
        self.ax = self.fig.add_subplot(gs[0, 0])
        ws = self.cfg.world_size
        self.ax.set_xlim(0, ws)
        self.ax.set_ylim(0, ws)
        self.ax.set_aspect("equal")
        self.ax.set_facecolor(COLOR_BG)
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self._draw_grid()

        # 右侧信息面板
        self.ax_info = self.fig.add_subplot(gs[0, 1])
        self.ax_info.set_xlim(0, 1)
        self.ax_info.set_ylim(0, 1)
        self.ax_info.set_facecolor("#1a1a2e")
        self.ax_info.set_xticks([])
        self.ax_info.set_yticks([])
        for spine in self.ax_info.spines.values():
            spine.set_color("#333")

        # 图例区域
        self._draw_legend()

        # 场景元素 (初始化空，_redraw 更新)
        self._init_scene_artists()

        # 信息文本
        self.info_texts = []

        # 事件
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.fig.canvas.mpl_connect("button_press_event", self._on_press)
        self.fig.canvas.mpl_connect("button_release_event", self._on_release)
        self.fig.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.fig.canvas.mpl_connect("close_event", lambda e: self.stop())

        self.fig.tight_layout()

    def _draw_grid(self):
        """绘制地板网格和房间边界。"""
        ws = self.cfg.world_size
        # 地板背景
        floor = patches.Rectangle(
            (0, 0), ws, ws, facecolor="#f0ead6", edgecolor="none", zorder=0,
        )
        self.ax.add_patch(floor)
        # 网格线
        for i in range(int(ws) + 1):
            self.ax.axhline(i, color="#d4c9a8", lw=0.5, alpha=0.6)
            self.ax.axvline(i, color="#d4c9a8", lw=0.5, alpha=0.6)
        # 房间边界
        border = patches.Rectangle(
            (0, 0), ws, ws, facecolor="none", edgecolor="#8b7355", linewidth=3, zorder=1,
        )
        self.ax.add_patch(border)
        # 几个装饰物 (家具/障碍物)
        furniture = [
            ((1.5, 1.5), 1.0, 0.6, "#c4a882"),   # 沙发
            ((8.0, 8.5), 0.8, 0.8, "#a0a0a0"),   # 茶几
            ((1.0, 8.0), 0.5, 1.2, "#d4c5a9"),   # 柜子
        ]
        for (fx, fy), fw, fh, fc in furniture:
            f = patches.FancyBboxPatch(
                (fx - fw/2, fy - fh/2), fw, fh,
                boxstyle="round,pad=0.05", facecolor=fc,
                edgecolor="#999", linewidth=0.8, alpha=0.6, zorder=2,
            )
            self.ax.add_patch(f)

    def _init_scene_artists(self):
        # 车身相关 — 统一用列表管理，每次 _draw_car 清空重建
        self._car_artists = []

        # 宝宝
        (self.baby_dot,) = self.ax.plot([], [], "o", color=COLOR_BABY, ms=16, zorder=10,
                                         markeredgecolor="white", markeredgewidth=2)
        (self.baby_trail,) = self.ax.plot([], [], "-", color=COLOR_TRAIL_BABY, lw=1.5, alpha=0.5)

        # 车身轨迹
        (self.car_trail,) = self.ax.plot([], [], "-", color=COLOR_TRAIL_CAR, lw=1.5, alpha=0.4)

        # 距离线 (车到宝宝)
        (self.dist_line,) = self.ax.plot([], [], "--", color="#888", lw=1, alpha=0.5)

        # 标题 (带深色背景确保可读)
        self.title = self.ax.set_title("", color="white", fontsize=13, fontfamily="sans-serif",
                                        pad=12, fontweight="bold",
                                        bbox=dict(facecolor="#1a1a2e", edgecolor="#333", pad=4))

    def _draw_legend(self):
        """在主场景左上角画图例 (半透明背景)。"""
        items = [
            ("●  宝宝 (目标)", COLOR_BABY),
            ("▲  车头 / 大灯", "#fffbe6"),
            ("■  车身", COLOR_CAR_BODY),
            ("○  舵机底座", "#dee2e6"),
            ("▶  摄像头朝向", COLOR_CAMERA),
            ("■  尾灯 (后方)", "#ff3333"),
        ]
        bx, by = 0.02, 0.60
        bw, bh = 0.26, 0.35
        legend_box = patches.FancyBboxPatch(
            (bx, by), bw, bh,
            boxstyle="round,pad=0.08",
            facecolor="#1a1a2ecc", edgecolor="#444", linewidth=1,
            zorder=50, transform=self.ax.transAxes,
        )
        self.ax.add_patch(legend_box)
        self._legend_patches = [legend_box]
        for i, (label, color) in enumerate(items):
            t = self.ax.text(
                bx + 0.015, by + bh - 0.035 - i * 0.048, label,
                transform=self.ax.transAxes,
                fontsize=8.5, color=color, fontfamily="sans-serif",
                zorder=51, verticalalignment="top",
            )
            self._legend_patches.append(t)

    # ── 绘制小车 ──

    def _draw_car(self):
        """绘制小车模型: 带车头/车尾的轿车形状 + 舵机 + 摄像头。"""
        # 清除旧元素
        for artist in self._car_artists:
            artist.remove()
        self._car_artists.clear()

        cx, cy = self.ctrl.car_x, self.ctrl.car_y
        heading = self.ctrl.car_heading

        # 车身局部坐标 (forward = +y, 即车头朝 +y)
        # 尺寸: 总长约 1.2m, 宽约 0.7m
        BL = 1.2   # 总长
        BW = 0.70  # 总宽

        # heading=0 → 车头朝右(+x), 但局部坐标车头朝 +y
        # 需要 rotate_deg(heading - 90) 让局部 +y 映射到世界 heading 方向
        t_body = Affine2D().rotate_deg(heading - 90).translate(cx, cy) + self.ax.transData

        # ── 1. 阴影 ──
        shadow = patches.Polygon(
            [(-BW/2 + 0.03, -BL/2 - 0.03), (BW/2 + 0.03, -BL/2 - 0.03),
             (BW/2 + 0.03, BL/2 - 0.03), (0.03, BL/2 + 0.15),
             (-BW/2 + 0.03, BL/2 - 0.03)],
            facecolor="#00000033", edgecolor="none", zorder=2, transform=t_body,
        )
        self.ax.add_patch(shadow)
        self._car_artists.append(shadow)

        # ── 2. 车身主体 (前尖后方的轿车形状) ──
        body_poly = patches.Polygon(
            [
                (0, BL/2 + 0.08),          # 车头尖端 (nose)
                (BW*0.28, BL/2 - 0.05),     # 右前角
                (BW/2, BL*0.25),            # 右前轮眉
                (BW/2, -BL*0.35),           # 右后轮眉
                (BW*0.40, -BL/2),           # 右后角
                (-BW*0.40, -BL/2),          # 左后角
                (-BW/2, -BL*0.35),          # 左后轮眉
                (-BW/2, BL*0.25),           # 左前轮眉
                (-BW*0.28, BL/2 - 0.05),    # 左前角
            ],
            facecolor=COLOR_CAR_BODY, edgecolor="white", linewidth=1.8,
            zorder=4, transform=t_body,
        )
        self.ax.add_patch(body_poly)
        self._car_artists.append(body_poly)

        # ── 3. 车窗/座舱 (偏后) ──
        cabin = patches.FancyBboxPatch(
            (-BW*0.30, -BL*0.12), BW*0.60, BL*0.42,
            boxstyle="round,pad=0.04",
            facecolor="#1a3a5c", edgecolor="#4a8acccc", linewidth=1.2,
            zorder=5, transform=t_body,
        )
        self.ax.add_patch(cabin)
        self._car_artists.append(cabin)

        # ── 4. 前挡风玻璃 (车头方向) ──
        windshield = patches.Polygon(
            [(-BW*0.26, BL*0.25), (BW*0.26, BL*0.25),
             (BW*0.20, BL*0.08), (-BW*0.20, BL*0.08)],
            facecolor="#5bc0eb88", edgecolor="#89d6fbbb", linewidth=0.8,
            zorder=6, transform=t_body,
        )
        self.ax.add_patch(windshield)
        self._car_artists.append(windshield)

        # ── 5. 前大灯 (白色发光) ──
        for hx in [-BW*0.35, BW*0.35]:
            hl = patches.Circle(
                (hx, BL*0.38), 0.06,
                facecolor="#fffbe6", edgecolor="#ffd000", linewidth=1.5,
                zorder=7, transform=t_body,
            )
            self.ax.add_patch(hl)
            self._car_artists.append(hl)

        # ── 6. 尾灯 (红色) ──
        for tx in [-BW*0.30, BW*0.30]:
            tl = patches.Circle(
                (tx, -BL*0.42), 0.05,
                facecolor="#ff3333", edgecolor="#cc0000", linewidth=1,
                zorder=7, transform=t_body,
            )
            self.ax.add_patch(tl)
            self._car_artists.append(tl)

        # ── 7. 四个轮子 (对齐车身轮眉位置) ──
        wheel_l, wheel_w = 0.18, 0.08
        wheel_positions = [
            (-BW/2 - 0.03, BL*0.22),           # 前左
            (BW/2 - wheel_w + 0.03, BL*0.22),  # 前右
            (-BW/2 - 0.03, -BL*0.32),          # 后左
            (BW/2 - wheel_w + 0.03, -BL*0.32), # 后右
        ]
        for wx, wy in wheel_positions:
            wheel = patches.FancyBboxPatch(
                (wx, wy), wheel_w, wheel_l,
                boxstyle="round,pad=0.015",
                facecolor="#1a1a1a", edgecolor="#444", linewidth=0.8,
                zorder=6, transform=t_body,
            )
            self.ax.add_patch(wheel)
            self._car_artists.append(wheel)

        # ── 8. 舵机底座 (车前部, 在车身上面) ──
        servo_r = 0.10
        servo_base_y = BL*0.30
        servo_base = patches.Circle(
            (0, servo_base_y), servo_r,
            facecolor="#dee2e6", edgecolor="#495057", linewidth=1.5,
            zorder=8, transform=t_body,
        )
        self.ax.add_patch(servo_base)
        self._car_artists.append(servo_base)

        # ── 9. 摄像头方向指示 (舵机独立旋转) ──
        # servo_world_angle: FOV 楔形用的世界坐标角度 (cos/sin 直接使用)
        servo_world_angle = heading + (self.ctrl.servo_x - 90.0) * self.cfg.servo_dir_x
        cam_len = 0.28
        t_cam = (
            Affine2D().rotate_deg(servo_world_angle - 90).translate(cx, cy)
            + self.ax.transData
        )
        # 三角: 宽底靠舵机, 尖端指向车头 (+y 方向)
        cam_tri = patches.Polygon(
            [(-0.06, servo_base_y), (0.06, servo_base_y),
             (0, servo_base_y + cam_len)],
            facecolor=COLOR_CAMERA, edgecolor="white", linewidth=1.2,
            zorder=9, transform=t_cam,
        )
        self.ax.add_patch(cam_tri)
        self._car_artists.append(cam_tri)

        # ── 10. 摄像头 FOV 锥 ──
        if self.show_fov:
            fov_half = self.cfg.camera_fov_deg / 2
            fov_len = 3.0
            fov_angles = np.linspace(-fov_half, fov_half, 30)
            fov_pts = [(cx, cy)]
            for a in fov_angles:
                abs_angle = math.radians(servo_world_angle + a)
                fov_pts.append((cx + fov_len * math.cos(abs_angle),
                                cy + fov_len * math.sin(abs_angle)))
            fov_wedge = patches.Polygon(
                fov_pts,
                facecolor=COLOR_CAMERA_FOV, edgecolor=COLOR_CAMERA, linewidth=0.6,
                alpha=0.25, zorder=1,
            )
            self.ax.add_patch(fov_wedge)
            self._car_artists.append(fov_wedge)

    # ── 信息面板 ──

    def _draw_info(self):
        for t in self.info_texts:
            t.remove() if hasattr(t, "remove") else None
        self.info_texts.clear()

        ctrl = self.ctrl
        cfg = self.cfg

        # 状态颜色
        state_colors = {MotionState.TRACK: "#06d6a0", MotionState.SCAN: "#ffd166",
                        MotionState.IDLE: "#aaa"}
        follow_colors = {FollowState.FORWARD: "#06d6a0", FollowState.BACKWARD: "#ef476f",
                         FollowState.HOLD: "#aaa", FollowState.COOLDOWN: "#ffd166"}

        servo_dev = ctrl._servo_body_dev()

        lines = [
            ("Raspbot 小车演示", 12, COLOR_CAMERA, True),
            ("", 6, "#ccc", False),
            ("── 状态 ──", 10, "#ffd166", True),
            (f"主状态:     {ctrl.state.name}", 10, state_colors.get(ctrl.state, "#aaa"), False),
            (f"宝宝:       {'[ 可见 ]' if self.baby.visible else '[ 隐藏 ]'}", 10, COLOR_BABY if self.baby.visible else COLOR_BABY_HIDDEN, False),
            (f"距离跟随:   {ctrl._follow_state.name}", 10, follow_colors.get(ctrl._follow_state, "#aaa"), False),
            ("", 6, "#ccc", False),
            ("── 舵机 (内环) ──", 10, "#ffd166", True),
            (f"角度: {ctrl.servo_x:6.1f}°   偏移: {servo_dev:+6.1f}°", 10, "#ccc", False),
            (f"死区: ±{cfg.body_dead_zone:.1f}°", 10, "#999", False),
            ("", 6, "#ccc", False),
            ("── 车身 (外环) ──", 10, "#ffd166", True),
            (f"朝向: {ctrl.car_heading:6.1f}°   输出: {ctrl.motor_out:+6.1f}", 10, "#ccc", False),
            (f"转速: {abs(ctrl.motor_out) * 3.0:4.1f}°/s", 10, "#999", False),
            ("", 6, "#ccc", False),
            ("── 距离 ──", 10, "#ffd166", True),
            (f"当前: {self.dist_cm:5.1f} cm", 10, "#ccc", False),
            (f"目标: {cfg.follow_dist_near:.0f} – {cfg.follow_dist_far:.0f} cm", 10, "#999", False),
            ("", 6, "#ccc", False),
            ("── PID ──", 10, "#ffd166", True),
            (f"舵机 Kp={cfg.servo_kp_x}  Kd={cfg.servo_kd_x}", 10, "#999", False),
            (f"车身 Kp={cfg.body_kp}  Kd_imu={cfg.body_kd_imu}", 10, "#999", False),
            ("", 6, "#ccc", False),
            ("── 控制 ──", 10, "#ffd166", True),
            (f"速度: {self.dt_scale:.1f}×    {'[ 暂停 ]' if self.paused else '[ 运行 ]'}", 10, "#ccc", False),
            ("", 8, "#ccc", False),
            ("鼠标拖拽 移动宝宝", 9, "#888", False),
            ("0=手动 1=绕圈 2=折线", 9, "#888", False),
            ("3=躲藏 空格暂停", 9, "#888", False),
            ("↑↓速度 F=切换FOV", 9, "#888", False),
        ]

        for i, (text, fontsize, color, bold) in enumerate(lines):
            t = self.ax_info.text(
                0.05, 0.96 - i * 0.026, text,
                transform=self.ax_info.transAxes,
                fontsize=fontsize, color=color, fontfamily="sans-serif",
                fontweight="bold" if bold else "normal",
                verticalalignment="top",
            )
            self.info_texts.append(t)

        # 右侧简易舵机角度条
        self._draw_servo_bar()

    def _draw_servo_bar(self):
        """在信息面板底部画简易舵机角度条。"""
        bar_y = 0.06
        bar_h = 0.03
        bar_x0, bar_x1 = 0.1, 0.9

        # 背景
        bar_bg = patches.Rectangle(
            (bar_x0, bar_y), bar_x1 - bar_x0, bar_h,
            transform=self.ax_info.transAxes,
            facecolor="#333", edgecolor="#555", linewidth=0.5, zorder=1,
        )
        self.ax_info.add_patch(bar_bg)
        self.info_texts.append(bar_bg)

        # 中心线 (用 plot 代替 axvline, 因为 axvline 不支持 transform)
        cx = bar_x0 + (bar_x1 - bar_x0) / 2
        (self._servo_center_line,) = self.ax_info.plot(
            [cx, cx], [bar_y, bar_y + bar_h],
            color="white", lw=1, alpha=0.5, transform=self.ax_info.transAxes,
            clip_on=False,
        )
        self.info_texts.append(self._servo_center_line)

        # 舵机位置
        sx_norm = self.ctrl.servo_x / 180.0  # 0-1
        sx_pos = bar_x0 + (bar_x1 - bar_x0) * sx_norm
        bar_marker = patches.Rectangle(
            (sx_pos - 0.008, bar_y - 0.003), 0.016, bar_h + 0.006,
            transform=self.ax_info.transAxes,
            facecolor=COLOR_CAMERA, edgecolor="white", linewidth=1, zorder=2,
        )
        self.ax_info.add_patch(bar_marker)
        self.info_texts.append(bar_marker)

        # 死区标记
        dead_left = bar_x0 + (bar_x1 - bar_x0) * (90 - self.cfg.follow_servo_center_deg) / 180
        dead_right = bar_x0 + (bar_x1 - bar_x0) * (90 + self.cfg.follow_servo_center_deg) / 180
        dead_zone = patches.Rectangle(
            (dead_left, bar_y), dead_right - dead_left, bar_h,
            transform=self.ax_info.transAxes,
            facecolor="#06d6a044", edgecolor="none", zorder=0,
        )
        self.ax_info.add_patch(dead_zone)
        self.info_texts.append(dead_zone)

        # 标签 (也加入 info_texts 以便清理)
        self.info_texts.append(
            self.ax_info.text(bar_x0, bar_y + bar_h + 0.005, "0°", transform=self.ax_info.transAxes,
                              fontsize=6, color="#888", ha="center"))
        self.info_texts.append(
            self.ax_info.text(bar_x1, bar_y + bar_h + 0.005, "180°", transform=self.ax_info.transAxes,
                              fontsize=6, color="#888", ha="center"))
        self.info_texts.append(
            self.ax_info.text(bar_x0 + (bar_x1 - bar_x0) / 2, bar_y + bar_h + 0.005, "90°",
                              transform=self.ax_info.transAxes, fontsize=6, color="#888", ha="center"))

    # ── 事件处理 ──

    def _on_key(self, event):
        if event.key == " ":
            self.paused = not self.paused
        elif event.key == "up":
            self.dt_scale = min(5.0, self.dt_scale + 0.5)
        elif event.key == "down":
            self.dt_scale = max(0.1, self.dt_scale - 0.5)
        elif event.key == "left":
            # 距离由世界坐标实时计算，←→ 不再手动调整
            pass
        elif event.key == "right":
            pass
        elif event.key == "q":
            self.stop()
        elif event.key == "f":
            self.show_fov = not self.show_fov
        elif event.key == "1":
            self.baby.switch_mode("circle")
        elif event.key == "2":
            self.baby.switch_mode("zigzag")
        elif event.key == "3":
            self.baby.switch_mode("hide")
        elif event.key == "0":
            self.baby.switch_mode("manual")

    def _on_press(self, event):
        """鼠标按下 — 拖拽宝宝或单击移动。"""
        if event.inaxes == self.ax and event.button == 1:
            self._dragging = True
            self.baby.x = event.xdata
            self.baby.y = event.ydata
            self.baby.visible = True

    def _on_release(self, event):
        """鼠标松开 — 停止拖拽。"""
        self._dragging = False

    def _on_motion(self, event):
        """鼠标拖拽 — 实时移动宝宝。"""
        if self._dragging and event.inaxes == self.ax:
            self.baby.x = event.xdata
            self.baby.y = event.ydata

    def stop(self):
        self.running = False
        try:
            plt.close("all")
        except Exception:
            pass

    # ── 主循环 ──

    def run(self):
        last_frame = time.perf_counter()

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
            self.sim_time += dt

            # 更新模拟
            self.baby.step(dt)
            # 超声波在车头位置，从车头前端测距 (非车中心)
            heading_rad = math.radians(self.ctrl.car_heading)
            front_offset = 0.68  # 车头到中心的局部距离 (BL/2 + 0.08)
            front_x = self.ctrl.car_x + front_offset * math.cos(heading_rad)
            front_y = self.ctrl.car_y + front_offset * math.sin(heading_rad)
            dx = self.baby.x - front_x
            dy = self.baby.y - front_y
            self.dist_cm = max(2.0, math.sqrt(dx*dx + dy*dy) * 100)
            self.ctrl.update(self.baby, self.dist_cm, dt, self.sim_time)

            # 绘制
            self._redraw()
            plt.pause(max(0.016, dt / self.dt_scale * 0.3))

    def _redraw(self):
        # 轨迹
        self._trail_car_x.append(self.ctrl.car_x)
        self._trail_car_y.append(self.ctrl.car_y)
        if len(self._trail_car_x) > self._max_trail:
            self._trail_car_x = self._trail_car_x[-self._max_trail:]
            self._trail_car_y = self._trail_car_y[-self._max_trail:]
        self.car_trail.set_data(self._trail_car_x, self._trail_car_y)

        bx, by = self.baby.world_pos()
        self._trail_baby_x.append(bx)
        self._trail_baby_y.append(by)
        if len(self._trail_baby_x) > self._max_trail:
            self._trail_baby_x = self._trail_baby_x[-self._max_trail:]
            self._trail_baby_y = self._trail_baby_y[-self._max_trail:]
        self.baby_trail.set_data(self._trail_baby_x, self._trail_baby_y)

        # 宝宝
        color = COLOR_BABY if self.baby.visible else COLOR_BABY_HIDDEN
        self.baby_dot.set_data([bx], [by])
        self.baby_dot.set_color(color)

        # 距离线
        self.dist_line.set_data([self.ctrl.car_x, bx], [self.ctrl.car_y, by])

        # 小车
        self._draw_car()

        # 标题
        mode_names = {"manual": "手动(鼠标)", "circle": "绕圈", "zigzag": "折线", "hide": "躲藏"}
        mode_cn = mode_names.get(self.baby._mode, self.baby._mode)
        self.title.set_text(
            f"宝宝模式: {mode_cn}  |  状态: {self.ctrl.state.name}  |  "
            f"舵机: {self.ctrl.servo_x:.0f}°  |  车身朝向: {self.ctrl.car_heading:.0f}°  |  "
            f"距离: {self.dist_cm:.0f} cm"
        )

        # 信息面板
        self._draw_info()

        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════


def main():
    ap = argparse.ArgumentParser(description="Raspbot 小车双环伺服跟踪演示")
    ap.add_argument("--no-motor", action="store_true", help="关闭车身旋转 (仅舵机跟踪)")
    ap.add_argument("--speed", type=float, default=1.0, help="模拟速度倍率")
    args = ap.parse_args()

    cfg = DemoConfig()
    if args.no_motor:
        cfg.enable_motor_control = False
        cfg.enable_distance_follow = False

    demo = CarDemo(cfg)
    demo.dt_scale = args.speed

    print("=" * 58)
    print("  Raspbot 小车双环伺服跟踪演示")
    print("  基于 motion_controller.py 真实控制逻辑")
    print("=" * 58)
    print()
    print("  控制键:")
    print("    空格       — 暂停 / 继续")
    print("    ↑ / ↓      — 加速 / 减速")
    print("    0 / 1 / 2 / 3  — 宝宝模式: 手动(鼠标) / 绕圈 / 折线 / 躲藏")
    print("    F          — 切换摄像头 FOV 显示")
    print("    鼠标拖拽    — 移动宝宝")
    print("    Q          — 退出")
    print()
    print("  双环控制:")
    print("    内环: 宝宝像素偏差 → PD → 舵机旋转")
    print("    外环: 舵机偏移 → 车身旋转 (死区 + IMU 阻尼)")
    print("    距离跟随: 舵机居中时前进/后退保持距离")
    print()

    demo.run()


if __name__ == "__main__":
    main()
