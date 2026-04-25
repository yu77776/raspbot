#!/usr/bin/env python3
"""
oled_face.py · 事件驱动 OLED 表情引擎

设计理念：
  - 常态显示表情（待机眨眼 / 追踪注视 / 转身晕眼 / 睡眠）
  - 事件临时接管屏幕（音量条 / 音乐动画 / 传感器数值 / 报警闪烁）
  - 事件结束后自动回到表情

128×32 像素，面向婴儿，不面向家长。
"""

import math
import random
import threading
import time

try:
    from luma.core.interface.serial import i2c as luma_i2c
    from luma.oled.device import ssd1306
    from PIL import Image, ImageDraw, ImageFont
    HAS_OLED = True
except Exception:
    HAS_OLED = False


# ── 事件类型 ──────────────────────────────

class OledEvent:
    """临时接管屏幕的事件"""
    def __init__(self, kind: str, value=None, duration: float = 2.5):
        self.kind = kind        # 'volume' | 'music' | 'sensor' | 'alert' | 'listening'
        self.value = value      # 事件数据（音量值、传感器 dict、报警文字等）
        self.duration = duration
        self.start_t = time.monotonic()

    @property
    def elapsed(self):
        return time.monotonic() - self.start_t

    @property
    def expired(self):
        return self.elapsed >= self.duration


class FaceEngine:
    def __init__(self):
        self.device = None
        self.font_cn = None
        self.font_en = None
        self.font_cn_name = 'unset'
        self.font_en_name = 'unset'

        # 基础状态
        self.face_state = 'idle'   # idle | tracking | turning | sleeping
        self.alarm = ''
        self.env_data = {}
        self.eye_offset = 0

        # 事件队列（只保留最新一个）
        self._event = None
        self._event_lock = threading.Lock()

        self.lock = threading.Lock()
        self.stop_event = threading.Event()

        if not HAS_OLED:
            print('[OLED] unavailable')
            return

        try:
            serial = luma_i2c(port=1, address=0x3C)
            self.device = ssd1306(serial, width=128, height=32)

            self.font_cn, self.font_cn_name = self._load_font([
                '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
                '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
                '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
                '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            ], 12)
            self.font_en, self.font_en_name = self._load_font([
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                '/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf',
                '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
            ], 11)
            self.font_big, _ = self._load_font([
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            ], 18)

            print(f'[OLED] OK cn={self.font_cn_name} en={self.font_en_name}')
        except Exception as e:
            print(f'[OLED] FAIL: {e}')
            self.device = None

    # ── 字体 ──────────────────────────────

    def _load_font(self, candidates, size):
        for path in candidates:
            try:
                return ImageFont.truetype(path, size), path
            except Exception:
                continue
        return ImageFont.load_default(), 'PIL_default'

    def _draw_text_mixed(self, draw, pos, text, font_override=None):
        x, y = pos
        for ch in str(text):
            if font_override:
                font = font_override
            else:
                font = self.font_en if ord(ch) < 128 else self.font_cn
            draw.text((x, y), ch, font=font, fill=1)
            try:
                advance = draw.textlength(ch, font=font)
            except Exception:
                box = draw.textbbox((0, 0), ch, font=font)
                advance = (box[2] - box[0]) if box else 0
            x += max(1, int(round(advance)))

    def _draw_text_center(self, draw, y, text, font=None):
        """水平居中绘制文字"""
        font = font or self.font_en
        try:
            tw = draw.textlength(text, font=font)
        except Exception:
            box = draw.textbbox((0, 0), text, font=font)
            tw = box[2] - box[0]
        x = max(0, (128 - int(tw)) // 2)
        draw.text((x, y), text, font=font, fill=1)

    # ── 外部接口 ─────────────────────────

    def set_state(self, s):
        """设置基础表情状态: idle / tracking / turning / sleeping"""
        with self.lock:
            self.face_state = s

    def set_alarm(self, msg):
        """设置报警文字，非空时触发报警事件"""
        with self.lock:
            old = self.alarm
            self.alarm = msg
        if msg and msg != old:
            self.push_event('alert', msg, duration=5.0)

    def set_pan(self, angle):
        """舵机角度 → 眼球偏移"""
        self.eye_offset = int((angle - 90) / 45 * 9)
        self.eye_offset = max(-10, min(10, self.eye_offset))

    def set_env_data(self, data):
        with self.lock:
            self.env_data = data

    def push_event(self, kind, value=None, duration=2.5):
        """
        推送临时事件，立即接管屏幕。

        kind:
          'volume'    - value: int 0-100，显示音量条
          'music'     - value: str 歌名（可选），显示音符动画
          'sensor'    - value: dict {'label': 'Temp', 'text': '25.3°C'}
          'alert'     - value: str 报警文字，闪烁显示
          'listening' - value: None，显示麦克风/声波动画
        """
        with self._event_lock:
            self._event = OledEvent(kind, value, duration)

    def _pop_event(self):
        with self._event_lock:
            ev = self._event
            if ev and ev.expired:
                self._event = None
                return None
            return ev

    # ── 表情绘制 ──────────────────────────

    def _new_frame(self):
        return Image.new('1', (128, 32), 0)

    def _display(self, img):
        if self.device:
            self.device.display(img)

    def _draw_face_idle(self, tick):
        """😊 待机：圆眼 + 随机眨眼"""
        img = self._new_frame()
        draw = ImageDraw.Draw(img)
        lx = 38 + self.eye_offset
        rx = 90 + self.eye_offset

        # 眨眼
        blink_cycle = tick % 5.0
        if blink_cycle > 4.8:
            ry = 2  # 眯眼
        else:
            ry = 10

        draw.ellipse([lx - 14, 16 - ry, lx + 14, 16 + ry], fill=1)
        draw.ellipse([rx - 14, 16 - ry, rx + 14, 16 + ry], fill=1)

        # 小嘴巴
        draw.arc([54, 22, 74, 32], 0, 180, fill=1, width=1)

        self._display(img)

    def _draw_face_tracking(self, tick):
        """👀 追踪：眼球跟随 + 微笑"""
        img = self._new_frame()
        draw = ImageDraw.Draw(img)
        lx = 38 + self.eye_offset
        rx = 90 + self.eye_offset

        # 眼眶
        draw.ellipse([lx - 14, 6, lx + 14, 26], outline=1, width=1)
        draw.ellipse([rx - 14, 6, rx + 14, 26], outline=1, width=1)

        # 眼球（实心小圆，跟随偏移更明显）
        pb = self.eye_offset // 2
        draw.ellipse([lx - 5 + pb, 11, lx + 5 + pb, 21], fill=1)
        draw.ellipse([rx - 5 + pb, 11, rx + 5 + pb, 21], fill=1)

        # 微笑弧
        draw.arc([50, 22, 78, 34], 10, 170, fill=1, width=1)

        self._display(img)

    def _draw_face_turning(self, tick):
        """😵 转身：螺旋眼"""
        img = self._new_frame()
        draw = ImageDraw.Draw(img)
        lx, rx = 38, 90
        angle = (tick * 300) % 360

        for cx in (lx, rx):
            # 螺旋线
            for i in range(0, 360, 30):
                a = math.radians(angle + i)
                r = 4 + (i / 360) * 8
                x = cx + int(r * math.cos(a))
                y = 16 + int(r * math.sin(a))
                draw.point((x, y), fill=1)
            # 外圈
            draw.ellipse([cx - 13, 3, cx + 13, 29], outline=1, width=1)

        self._display(img)

    def _draw_face_sleeping(self, tick):
        """😴 睡眠：闭眼 + zzZ"""
        img = self._new_frame()
        draw = ImageDraw.Draw(img)
        lx = 38
        rx = 90

        # 闭眼（横线）
        draw.line([lx - 10, 16, lx + 10, 16], fill=1, width=1)
        draw.line([rx - 10, 16, rx + 10, 16], fill=1, width=1)

        # zzZ 浮动
        phase = int(tick * 2) % 3
        z_chars = ['z', 'z', 'Z']
        z_positions = [(105, 18), (112, 10), (118, 2)]
        for i in range(phase + 1):
            if i < len(z_positions):
                draw.text(z_positions[i], z_chars[i], font=self.font_en, fill=1)

        self._display(img)

    # ── 事件绘制 ──────────────────────────

    def _draw_event_volume(self, ev):
        """🔊 音量条"""
        img = self._new_frame()
        draw = ImageDraw.Draw(img)
        vol = int(ev.value or 0)
        vol = max(0, min(100, vol))

        # 标题
        self._draw_text_center(draw, 0, 'VOL', self.font_en)

        # 进度条框
        bar_x, bar_y = 14, 16
        bar_w, bar_h = 100, 12
        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=1)

        # 填充
        fill_w = int(bar_w * vol / 100)
        if fill_w > 0:
            draw.rectangle([bar_x + 1, bar_y + 1, bar_x + fill_w, bar_y + bar_h - 1], fill=1)

        # 数值
        self._draw_text_center(draw, 16, f'{vol}%', self.font_en)

        self._display(img)

    def _draw_note(self, draw, cx, cy):
        """画一个简笔音符：实心圆 + 竖线 + 小旗"""
        draw.ellipse([cx - 3, cy, cx + 3, cy + 4], fill=1)
        draw.line([cx + 3, cy + 2, cx + 3, cy - 10], fill=1, width=1)
        draw.line([cx + 3, cy - 10, cx + 7, cy - 7], fill=1, width=1)

    def _draw_event_music(self, ev):
        """音乐动画：音符浮动"""
        img = self._new_frame()
        draw = ImageDraw.Draw(img)
        t = ev.elapsed

        # 三个音符，不同相位浮动
        for i in range(3):
            x = 25 + i * 35
            y = 14 + int(5 * math.sin(t * 3 + i * 1.5))
            self._draw_note(draw, x, y)

        # 歌名
        name = str(ev.value or '')
        if name:
            display_name = name[:10]
            self._draw_text_center(draw, 22, display_name, self.font_en)

        self._display(img)

    def _draw_event_sensor(self, ev):
        """传感器大字显示"""
        img = self._new_frame()
        draw = ImageDraw.Draw(img)

        data = ev.value or {}
        label = str(data.get('label', ''))
        text = str(data.get('text', ''))[:10]

        # 标签小字居中
        self._draw_text_center(draw, 0, label, self.font_en)

        # 数值：尝试大字体，如果太宽就退回小字体
        font = self.font_big
        try:
            tw = draw.textlength(text, font=font)
        except Exception:
            tw = 999
        if tw > 120:
            font = self.font_en
        self._draw_text_center(draw, 14, text, font)

        self._display(img)

    def _draw_event_alert(self, ev):
        """报警闪烁：交替显示文字帧和空帧"""
        msg = str(ev.value or 'ALERT')[:12]
        show_text = int(ev.elapsed / 0.3) % 2 == 0

        img = self._new_frame()
        draw = ImageDraw.Draw(img)

        if show_text:
            # 文字帧：白字黑底
            self._draw_text_center(draw, 2, '!! WARNING !!', self.font_en)
            self._draw_text_center(draw, 18, msg, self.font_cn)
        else:
            # 反色帧：黑字白底
            draw.rectangle([0, 0, 127, 31], fill=1)
            # 用 fill=0 画黑色文字
            self._draw_text_center_inv(draw, 2, '!! WARNING !!', self.font_en)
            self._draw_text_center_inv(draw, 18, msg, self.font_cn)

        self._display(img)

    def _draw_text_center_inv(self, draw, y, text, font=None):
        """水平居中绘制文字（黑色，用于反色背景）"""
        font = font or self.font_en
        try:
            tw = draw.textlength(text, font=font)
        except Exception:
            box = draw.textbbox((0, 0), text, font=font)
            tw = box[2] - box[0]
        x = max(0, (128 - int(tw)) // 2)
        draw.text((x, y), text, font=font, fill=0)

    def _draw_event_listening(self, ev):
        """声波动画"""
        img = self._new_frame()
        draw = ImageDraw.Draw(img)
        t = ev.elapsed

        cx = 64
        # 简笔麦克风
        draw.rounded_rectangle([cx - 4, 6, cx + 4, 18], radius=3, outline=1)
        draw.arc([cx - 8, 14, cx + 8, 26], 0, 180, fill=1, width=1)
        draw.line([cx, 26, cx, 29], fill=1, width=1)
        draw.line([cx - 5, 29, cx + 5, 29], fill=1, width=1)

        # 两侧声波线
        for side in (-1, 1):
            for i in range(1, 4):
                amp = max(1, int(4 * abs(math.sin(t * 5 + i * 0.8))))
                bx = cx + side * (14 + i * 8)
                draw.line([bx, 16 - amp, bx, 16 + amp], fill=1, width=1)

        self._display(img)

    # ── 事件分发 ──────────────────────────

    def _draw_alarm_flash(self, msg, tick):
        """持续报警闪烁（不通过事件系统）"""
        msg = str(msg)[:12]
        show_text = int(tick / 0.3) % 2 == 0

        img = self._new_frame()
        draw = ImageDraw.Draw(img)

        if show_text:
            self._draw_text_center(draw, 2, '!! WARNING !!', self.font_en)
            self._draw_text_center(draw, 18, msg, self.font_cn)
        else:
            draw.rectangle([0, 0, 127, 31], fill=1)
            self._draw_text_center_inv(draw, 2, '!! WARNING !!', self.font_en)
            self._draw_text_center_inv(draw, 18, msg, self.font_cn)

        self._display(img)

    _EVENT_DRAWERS = {
        'volume':    '_draw_event_volume',
        'music':     '_draw_event_music',
        'sensor':    '_draw_event_sensor',
        'alert':     '_draw_event_alert',
        'listening': '_draw_event_listening',
    }

    def _draw_event(self, ev):
        drawer = self._EVENT_DRAWERS.get(ev.kind)
        if drawer:
            getattr(self, drawer)(ev)
        else:
            # fallback
            self._draw_event_sensor(ev)

    # ── 主循环 ────────────────────────────

    def _run(self):
        tick = 0.0

        while not self.stop_event.is_set():
            try:
                # 优先级：事件 > 报警 > 表情
                ev = self._pop_event()

                if ev:
                    self._draw_event(ev)
                else:
                    with self.lock:
                        alarm = self.alarm
                        state = self.face_state

                    if alarm:
                        self._draw_alarm_flash(alarm, tick)
                    elif state == 'tracking':
                        self._draw_face_tracking(tick)
                    elif state == 'turning':
                        self._draw_face_turning(tick)
                    elif state == 'sleeping':
                        self._draw_face_sleeping(tick)
                    else:
                        self._draw_face_idle(tick)
            except Exception as e:
                # 绘制错误不能让整个线程崩溃
                if int(tick) % 5 == 0:
                    print(f'[OLED] draw error: {e}')

            time.sleep(0.05)
            tick += 0.05

    def start(self):
        if not self.device:
            return
        self.stop_event.clear()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self.stop_event.set()
