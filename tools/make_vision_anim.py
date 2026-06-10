"""
视觉跟随动画 v2 —— 为答辩 PPT 现做，渲染为高质量 GIF。
左：摄像头视角（网格 + 入锁动画 + 舵机仪表弧 + 像素误差滚动曲线）
右：俯视跟随（渐变 FOV 锥 + 带轮子的小车 + 运动拖影 + 距离状态机）
配色与 PPT「夜间监护」主题一致。Agg 后端无窗口，输出循环 GIF。
"""
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mp
from matplotlib.transforms import Affine2D
from matplotlib.collections import LineCollection
import imageio.v2 as imageio
import os

for fn in ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC"]:
    try:
        matplotlib.font_manager.findfont(fn, fallback_to_default=False)
        plt.rcParams["font.family"] = fn
        break
    except Exception:
        pass
plt.rcParams["axes.unicode_minus"] = False

BG = "#0F1714"; PANEL = "#1B2A23"; LINE = "#2A3A32"; GRID = "#16221c"
INK = "#EAF2EC"; DIM = "#8FA89A"; LIME = "#9EE37D"; AMBER = "#F2B872"
SKY = "#7FC8E8"; ROSE = "#E8927C"

FW, FH = 640, 480
CX, CY = FW / 2, FH / 2
N = 96

def ease(x):  # smootherstep
    return x * x * x * (x * (x * 6 - 15) + 10)

# 宝宝轨迹：分段缓动的关键点之间插值，比纯正弦更自然
KEYS = [(0.18, 0.55), (0.78, 0.40), (0.55, 0.70), (0.30, 0.35),
        (0.70, 0.58), (0.45, 0.50), (0.18, 0.55)]
def baby_norm(t):
    seg = t * (len(KEYS) - 1)
    i = min(int(seg), len(KEYS) - 2)
    f = ease(seg - i)
    ax_, ay_ = KEYS[i]; bx_, by_ = KEYS[i + 1]
    return ax_ + (bx_ - ax_) * f, ay_ + (by_ - ay_) * f

class PD:
    def __init__(s, kp, kd): s.kp, s.kd, s.le = kp, kd, 0.0
    def step(s, e):
        d = e - s.le; s.le = e
        return s.kp * e + s.kd * d

pan_pd = PD(0.10, 0.012)
servo = 90.0
car_yaw = 0.0
dist = 1.6
err_hist = []        # 像素误差历史（滚动曲线）
conf = 0.0

def gauge(ax, cx, cy, r, val, vmin, vmax, color, label):
    """半圆仪表弧，val 映射到 180°→0°"""
    frac = (val - vmin) / (vmax - vmin)
    frac = max(0.0, min(1.0, frac))
    # 背景弧
    th = np.linspace(math.pi, 0, 60)
    ax.plot(cx + r*np.cos(th), cy + r*np.sin(th), color=LINE, lw=4, solid_capstyle="round")
    # 值弧
    th2 = np.linspace(math.pi, math.pi - frac*math.pi, 40)
    ax.plot(cx + r*np.cos(th2), cy + r*np.sin(th2), color=color, lw=4, solid_capstyle="round")
    # 指针
    a = math.pi - frac*math.pi
    ax.plot([cx, cx + (r-3)*math.cos(a)], [cy, cy + (r-3)*math.sin(a)], color=INK, lw=1.6)
    ax.add_patch(mp.Circle((cx, cy), 2.4, fc=INK, ec="none"))
    ax.text(cx, cy - 13, label, color=color, fontsize=8.5, ha="center", fontweight="bold")

def render(i):
    global servo, car_yaw, dist, conf
    t = i / N
    fig = plt.figure(figsize=(11.2, 4.7), dpi=100)
    fig.patch.set_facecolor(BG)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.05, 1], wspace=0.1,
                          left=0.035, right=0.975, top=0.88, bottom=0.06)

    # ───────── 左：摄像头视角 ─────────
    axc = fig.add_subplot(gs[0, 0])
    axc.set_facecolor("#0a110e")
    axc.set_xlim(0, FW); axc.set_ylim(FH, 0)
    axc.set_xticks([]); axc.set_yticks([])
    for sp in axc.spines.values(): sp.set_color(LINE)
    axc.set_title("摄像头视角 · 内环 PD 云台伺服", color=LIME, fontsize=12.5, pad=8, loc="left")

    for gx in range(0, FW+1, 80): axc.axvline(gx, color=GRID, lw=0.6)
    for gy in range(0, FH+1, 80): axc.axhline(gy, color=GRID, lw=0.6)
    axc.axvline(CX, color=LINE, lw=0.9, ls=(0, (5, 4)))
    axc.axhline(CY, color=LINE, lw=0.9, ls=(0, (5, 4)))
    axc.add_patch(mp.Circle((CX, CY), 7, fill=False, ec=DIM, lw=1.1))

    bnx, bny = baby_norm(t)
    bx, by = bnx * FW, bny * FH
    err_x = bx - CX
    err_y = by - CY
    servo = float(np.clip(servo - pan_pd.step(err_x) * 0.16, 25, 155))

    # 入锁动画：前 8 帧 CANDIDATE，渐变到 LOCKED
    locking = i < 8
    conf = min(0.92, conf + 0.14) if not locking else 0.35 + i * 0.05
    box_c = AMBER if locking else LIME
    ls = (0, (4, 3)) if locking else "solid"

    # 误差矢量
    axc.annotate("", xy=(bx, by), xytext=(CX, CY),
                 arrowprops=dict(arrowstyle="-|>", color=AMBER, lw=2.2, alpha=0.85))
    axc.text((CX+bx)/2, (CY+by)/2 - 14, f"误差 ({err_x:+.0f},{err_y:+.0f})px",
             color=AMBER, fontsize=8.8, ha="center")

    bw, bh = 100, 158
    axc.add_patch(mp.FancyBboxPatch((bx-bw/2, by-bh/2), bw, bh,
                  boxstyle="round,pad=2,rounding_size=9", fill=False, ec=box_c, lw=2.6, ls=ls))
    # 简笔宝宝
    axc.add_patch(mp.Circle((bx, by-bh*0.27), 18, fc="#2a4035", ec=box_c, lw=1.7))
    axc.add_patch(mp.FancyBboxPatch((bx-17, by-bh*0.16), 34, 62,
                  boxstyle="round,pad=1,rounding_size=11", fc="#2a4035", ec=box_c, lw=1.5))
    tag = "CANDIDATE" if locking else "LOCKED"
    axc.add_patch(mp.FancyBboxPatch((bx-bw/2, by-bh/2-22), 118, 17,
                  boxstyle="round,pad=1,rounding_size=4", fc=box_c, ec="none"))
    axc.text(bx-bw/2+5, by-bh/2-13.5, f"{tag} · baby {conf:.2f}",
             color="#0a110e", fontsize=8.2, va="center", fontweight="bold")

    axc.text(12, 26, "640 × 480", color=DIM, fontsize=8.5)
    # 舵机仪表弧（右上角）
    gauge(axc, FW-66, 52, 34, servo, 25, 155, SKY, f"舵机 {servo:.0f}°")

    # 像素误差滚动曲线（底部嵌入）
    err_hist.append(err_x)
    if len(err_hist) > 48: err_hist.pop(0)
    if len(err_hist) > 2:
        gx0, gy0, gw_, gh_ = 24, FH-78, 230, 60
        axc.add_patch(mp.FancyBboxPatch((gx0-6, gy0-8), gw_+12, gh_+16,
                      boxstyle="round,pad=2,rounding_size=6", fc="#0d1611", ec=LINE, lw=1))
        axc.text(gx0, gy0-2, "像素误差收敛", color=DIM, fontsize=7.5)
        xs = np.linspace(gx0, gx0+gw_, len(err_hist))
        mx = max(40, max(abs(min(err_hist)), abs(max(err_hist))))
        ys = gy0 + gh_/2 - np.array(err_hist)/mx * (gh_/2 - 4)
        axc.plot([gx0, gx0+gw_], [gy0+gh_/2]*2, color=LINE, lw=0.7)
        axc.plot(xs, ys, color=LIME, lw=1.6)
        axc.add_patch(mp.Circle((xs[-1], ys[-1]), 2.6, fc=AMBER, ec="none"))

    # ───────── 右：俯视跟随 ─────────
    axt = fig.add_subplot(gs[0, 1])
    axt.set_facecolor("#0a110e")
    axt.set_xlim(-3, 3); axt.set_ylim(-0.6, 5)
    axt.set_aspect("equal"); axt.set_xticks([]); axt.set_yticks([])
    for sp in axt.spines.values(): sp.set_color(LINE)
    axt.set_title("俯视跟随 · 外环车身 + 距离状态机", color=SKY, fontsize=12.5, pad=8, loc="left")
    for gx in np.arange(-3, 3.1, 1): axt.axvline(gx, color=GRID, lw=0.6)
    for gy in np.arange(0, 5.1, 1): axt.axhline(gy, color=GRID, lw=0.6)

    pan_off = servo - 90.0
    car_yaw += (-pan_off * 0.013 - car_yaw) * 0.16
    car_yaw = float(np.clip(car_yaw, -0.7, 0.7))
    ang = math.radians(pan_off) + car_yaw
    bxr = math.sin(ang) * (dist + 0.7)
    byr = math.cos(ang) * (dist + 0.7) + 0.45

    if dist > 1.85: fstate, fcol = "FORWARD", LIME
    elif dist < 1.25: fstate, fcol = "BACKWARD", ROSE
    else: fstate, fcol = "HOLD", AMBER
    # 距离按演示曲线明确走完 远(FORWARD)→中(HOLD)→近(BACKWARD)→中 循环
    dist = 1.55 + 0.62 * math.sin(t * 2*math.pi - math.pi/2)

    # 渐变 FOV 锥（多层 wedge）
    fov = math.radians(26)
    base = car_yaw + math.radians(pan_off)
    for k in range(5):
        rr = 4.6 * (1 - k*0.16)
        axt.add_patch(mp.Wedge((0, 0.25), rr, 90-math.degrees(base+fov),
                     90-math.degrees(base-fov), fc=SKY, alpha=0.05))
    for sgn in (-1, 1):
        a = base + sgn*fov
        axt.plot([0, math.sin(a)*4.6], [0.25, math.cos(a)*4.6+0.25], color=SKY, lw=1, alpha=0.4)

    # 宝宝 + 连线
    axt.plot([0, bxr], [0.25, byr], color=LIME, lw=1, ls=(0,(3,3)), alpha=0.5)
    axt.add_patch(mp.Circle((bxr, byr), 0.23, fc="#2a4035", ec=LIME, lw=1.7))
    axt.text(bxr, byr+0.36, "宝宝", color=LIME, fontsize=9, ha="center")

    # 小车（车身 + 四轮 + 拖影）
    for k in range(1, 3):   # 拖影
        tr0 = Affine2D().rotate(-car_yaw*(1-0.15*k)).translate(-math.sin(car_yaw)*0.12*k, 0.25-0.12*k) + axt.transData
        gh0 = mp.FancyBboxPatch((-0.42,-0.3), 0.84, 0.6, boxstyle="round,pad=0.02,rounding_size=0.1",
               fc="none", ec=LIME, lw=1.0, alpha=0.12*(3-k))
        gh0.set_transform(tr0); axt.add_patch(gh0)
    tr = Affine2D().rotate(-car_yaw).translate(0, 0.25) + axt.transData
    for wx in (-0.46, 0.46):
        for wy in (-0.22, 0.22):
            wheel = mp.FancyBboxPatch((wx-0.08, wy-0.13), 0.16, 0.26,
                    boxstyle="round,pad=0.01,rounding_size=0.05", fc="#324a3d", ec=DIM, lw=0.8)
            wheel.set_transform(tr); axt.add_patch(wheel)
    body = mp.FancyBboxPatch((-0.42,-0.3), 0.84, 0.6, boxstyle="round,pad=0.02,rounding_size=0.12",
            fc=PANEL, ec=LIME, lw=2); body.set_transform(tr); axt.add_patch(body)
    cam = mp.FancyBboxPatch((-0.1, 0.18), 0.2, 0.16, boxstyle="round,pad=0.01,rounding_size=0.04",
            fc=SKY, ec="none"); cam.set_transform(tr); axt.add_patch(cam)
    hx, hy = math.sin(car_yaw)*0.7, math.cos(car_yaw)*0.7+0.25
    axt.annotate("", xy=(hx, hy), xytext=(0,0.25),
                 arrowprops=dict(arrowstyle="-|>", color=AMBER, lw=2.2))

    # 读数条
    axt.add_patch(mp.FancyBboxPatch((-2.92, 4.18), 2.0, 0.62, boxstyle="round,pad=0.02,rounding_size=0.06",
                  fc="#0d1611", ec=LINE, lw=1))
    axt.text(-2.8, 4.62, f"距离 {dist:0.2f} m", color=SKY, fontsize=10.5, va="center")
    axt.text(-2.8, 4.36, f"车身偏航 {math.degrees(car_yaw):+0.1f}°", color=DIM, fontsize=8.5, va="center")
    axt.add_patch(mp.FancyBboxPatch((1.1, 4.18), 1.8, 0.62, boxstyle="round,pad=0.02,rounding_size=0.06",
                  fc=fcol, ec="none", alpha=0.9))
    axt.text(2.0, 4.5, fstate, color="#0a110e", fontsize=13, va="center", ha="center", fontweight="bold")

    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    return buf

frames = [render(i) for i in range(N)]
out = "E:/bishe/outputs/defense_ppt/assets/vision_follow_demo.gif"
os.makedirs(os.path.dirname(out), exist_ok=True)
imageio.mimsave(out, frames, duration=0.06, loop=0)
print("OK", out, len(frames), "frames", f"{os.path.getsize(out)//1024}KB")
