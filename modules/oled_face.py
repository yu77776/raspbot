#!/usr/bin/env python3
"""
OLED face engine for SSD1306 128x32.

Audience: babies (expression-first), not operators.
Render priority: alarm > event > face_state.
"""

import math
import logging
import random
import threading
import time

logger = logging.getLogger(__name__)

try:
    from luma.core.interface.serial import i2c as luma_i2c
    from luma.oled.device import ssd1306
    from PIL import Image, ImageDraw, ImageFont

    HAS_OLED = True
except Exception as exc:
    logger.warning("OLED dependencies unavailable: %s", exc)
    HAS_OLED = False


class OledEvent:
    """Temporary event that takes over the OLED for a short duration."""

    def __init__(self, kind: str, value=None, duration: float = 2.5):
        self.kind = kind
        self.value = value
        self.duration = float(duration)
        self.start_t = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start_t

    @property
    def expired(self) -> bool:
        return self.elapsed >= self.duration


class FaceEngine:
    def __init__(self):
        self.device = None
        self.font_cn = None
        self.font_en = None
        self.font_big = None
        self.font_cn_name = "unset"
        self.font_en_name = "unset"

        self.face_state = "idle"  # idle | tracking | turning | sleeping
        self.alarm = ""
        self.env_data = {}
        self.eye_offset = 0

        self._event = None
        self._event_lock = threading.Lock()

        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self._last_draw_error_log_ts = 0.0
        now = time.monotonic()
        self._blink_close_until = 0.0
        self._next_blink_at = now + random.uniform(4.5, 5.5)

        if not HAS_OLED:
            print("[OLED] unavailable")
            return

        try:
            serial = luma_i2c(port=1, address=0x3C)
            self.device = ssd1306(serial, width=128, height=32)

            self.font_cn, self.font_cn_name = self._load_font(
                [
                    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
                    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                ],
                12,
            )
            self.font_en, self.font_en_name = self._load_font(
                [
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
                    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
                ],
                11,
            )
            self.font_big, _ = self._load_font(
                [
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                ],
                18,
            )

            print(f"[OLED] OK cn={self.font_cn_name} en={self.font_en_name}")
        except Exception as exc:
            logger.error("[OLED] FAIL: %s", exc)
            self.device = None

    def _load_font(self, candidates, size):
        for path in candidates:
            try:
                return ImageFont.truetype(path, size), path
            except Exception as exc:
                logger.warning("[OLED] font load failed path=%s: %s", path, exc)
                continue
        return ImageFont.load_default(), "PIL_default"

    def _new_frame(self):
        return Image.new("1", (128, 32), 0)

    def _display(self, image):
        if self.device:
            self.device.display(image)

    def _font_for_char(self, ch, preferred=None):
        if ord(ch) < 128:
            return preferred or self.font_en
        return self.font_cn or preferred or self.font_en

    def _text_width_mixed(self, draw, text, font=None):
        width = 0
        for ch in str(text):
            ch_font = self._font_for_char(ch, font)
            try:
                advance = draw.textlength(ch, font=ch_font)
            except Exception as exc:
                logger.warning("[OLED] textlength failed, fallback to textbbox: %s", exc)
                box = draw.textbbox((0, 0), ch, font=ch_font)
                advance = (box[2] - box[0]) if box else 0
            width += max(1, int(round(advance)))
        return width

    def _draw_text_mixed(self, draw, x, y, text, font=None, fill=1):
        for ch in str(text):
            ch_font = self._font_for_char(ch, font)
            draw.text((x, y), ch, font=ch_font, fill=fill)
            try:
                advance = draw.textlength(ch, font=ch_font)
            except Exception as exc:
                logger.warning("[OLED] textlength failed, fallback to textbbox: %s", exc)
                box = draw.textbbox((0, 0), ch, font=ch_font)
                advance = (box[2] - box[0]) if box else 0
            x += max(1, int(round(advance)))

    def _fit_text(self, draw, text, max_width=124, font=None):
        out = ""
        for ch in str(text):
            candidate = out + ch
            if self._text_width_mixed(draw, candidate, font) > max_width:
                break
            out = candidate
        return out

    def _draw_text_center(self, draw, y, text, font=None):
        text = str(text)
        tw = self._text_width_mixed(draw, text, font)
        x = max(0, (128 - tw) // 2)
        self._draw_text_mixed(draw, x, y, text, font=font, fill=1)

    def _draw_text_center_inv(self, draw, y, text, font=None):
        text = str(text)
        tw = self._text_width_mixed(draw, text, font)
        x = max(0, (128 - tw) // 2)
        self._draw_text_mixed(draw, x, y, text, font=font, fill=0)

    # Public API
    def set_state(self, state):
        with self.lock:
            self.face_state = str(state or "idle")

    def set_alarm(self, msg):
        with self.lock:
            self.alarm = str(msg or "")

    def set_pan(self, angle):
        try:
            offset = int((float(angle) - 90.0) / 45.0 * 9.0)
        except Exception as exc:
            logger.warning("[OLED] invalid pan angle %r: %s", angle, exc)
            offset = 0
        with self.lock:
            self.eye_offset = max(-10, min(10, offset))

    def set_env_data(self, data):
        with self.lock:
            self.env_data = dict(data or {})

    def push_event(self, kind, value=None, duration=2.5):
        with self._event_lock:
            self._event = OledEvent(str(kind or "sensor"), value, float(duration))

    # Event queue
    def _pop_event(self):
        with self._event_lock:
            ev = self._event
            if ev and ev.expired:
                self._event = None
                return None
            return ev

    # Faces
    def _draw_face_idle(self, tick):
        del tick
        image = self._new_frame()
        draw = ImageDraw.Draw(image)

        with self.lock:
            offset = self.eye_offset

        lx = 38 + offset
        rx = 90 + offset

        # Random blink around every ~5 seconds, close for 0.2s.
        now = time.monotonic()
        if now >= self._next_blink_at:
            self._blink_close_until = now + 0.2
            self._next_blink_at = now + random.uniform(4.5, 5.5)
        ry = 2 if now < self._blink_close_until else 10

        draw.ellipse([lx - 14, 16 - ry, lx + 14, 16 + ry], fill=1)
        draw.ellipse([rx - 14, 16 - ry, rx + 14, 16 + ry], fill=1)
        self._display(image)

    def _draw_face_tracking(self, tick):
        del tick
        image = self._new_frame()
        draw = ImageDraw.Draw(image)

        with self.lock:
            offset = self.eye_offset

        lx = 38 + offset
        rx = 90 + offset

        draw.ellipse([lx - 14, 6, lx + 14, 26], outline=1, width=1)
        draw.ellipse([rx - 14, 6, rx + 14, 26], outline=1, width=1)

        pupil_bias = offset // 2
        draw.ellipse([lx - 5 + pupil_bias, 11, lx + 5 + pupil_bias, 21], fill=1)
        draw.ellipse([rx - 5 + pupil_bias, 11, rx + 5 + pupil_bias, 21], fill=1)

        self._display(image)

    def _draw_face_turning(self, tick):
        image = self._new_frame()
        draw = ImageDraw.Draw(image)
        lx, rx = 38, 90
        angle = (tick * 300.0) % 360.0

        for cx in (lx, rx):
            for i in range(0, 360, 30):
                a = math.radians(angle + i)
                r = 4.0 + (i / 360.0) * 8.0
                x = cx + int(r * math.cos(a))
                y = 16 + int(r * math.sin(a))
                draw.point((x, y), fill=1)
            draw.ellipse([cx - 13, 3, cx + 13, 29], outline=1, width=1)

        self._display(image)

    def _draw_face_sleeping(self, tick):
        image = self._new_frame()
        draw = ImageDraw.Draw(image)

        draw.line([28, 16, 48, 16], fill=1, width=1)
        draw.line([80, 16, 100, 16], fill=1, width=1)

        phase = int(tick * 2) % 3
        z_positions = [(105, 18), (112, 10), (118, 2)]
        z_chars = ["z", "z", "Z"]
        for i in range(phase + 1):
            draw.text(z_positions[i], z_chars[i], font=self.font_en, fill=1)

        self._display(image)

    # Event drawings
    def _draw_event_volume(self, ev):
        image = self._new_frame()
        draw = ImageDraw.Draw(image)

        vol = int(ev.value or 0)
        vol = max(0, min(100, vol))

        self._draw_text_center(draw, 0, "VOL", self.font_en)

        bar_x, bar_y, bar_w, bar_h = 14, 16, 100, 12
        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=1)
        fill_w = int(bar_w * vol / 100)
        if fill_w > 0:
            draw.rectangle([bar_x + 1, bar_y + 1, bar_x + fill_w, bar_y + bar_h - 1], fill=1)

        self._draw_text_center(draw, 16, f"{vol}%", self.font_en)
        self._display(image)

    def _draw_note(self, draw, cx, cy):
        draw.ellipse([cx - 3, cy, cx + 3, cy + 4], fill=1)
        draw.line([cx + 3, cy + 2, cx + 3, cy - 10], fill=1, width=1)
        draw.line([cx + 3, cy - 10, cx + 7, cy - 7], fill=1, width=1)

    def _draw_event_music(self, ev):
        image = self._new_frame()
        draw = ImageDraw.Draw(image)
        t = ev.elapsed

        for i in range(3):
            x = 25 + i * 35
            y = 14 + int(5 * math.sin(t * 3 + i * 1.5))
            self._draw_note(draw, x, y)

        name = str(ev.value or "")
        if name:
            self._draw_text_center(draw, 22, self._fit_text(draw, name, font=self.font_en), self.font_en)

        self._display(image)

    def _draw_event_sensor(self, ev):
        image = self._new_frame()
        draw = ImageDraw.Draw(image)

        data = ev.value if isinstance(ev.value, dict) else {}
        label = self._fit_text(draw, str(data.get("label", "")), font=self.font_en)
        text = str(data.get("text", ""))

        self._draw_text_center(draw, 0, label, self.font_en)

        font = self.font_big
        tw = self._text_width_mixed(draw, text, font=font)
        if tw > 120:
            font = self.font_en
        self._draw_text_center(draw, 14, self._fit_text(draw, text, font=font), font)

        self._display(image)

    def _draw_event_alert(self, ev):
        show_text = int(ev.elapsed / 0.3) % 2 == 0

        image = self._new_frame()
        draw = ImageDraw.Draw(image)
        msg = self._fit_text(draw, str(ev.value or "ALERT"), font=self.font_cn)

        if show_text:
            self._draw_text_center(draw, 2, "!! WARNING !!", self.font_en)
            self._draw_text_center(draw, 18, msg, self.font_cn)
        else:
            draw.rectangle([0, 0, 127, 31], fill=1)
            self._draw_text_center_inv(draw, 2, "!! WARNING !!", self.font_en)
            self._draw_text_center_inv(draw, 18, msg, self.font_cn)

        self._display(image)

    def _draw_event_listening(self, ev):
        image = self._new_frame()
        draw = ImageDraw.Draw(image)
        t = ev.elapsed

        cx = 64
        draw.rectangle([cx - 4, 6, cx + 4, 18], outline=1)
        draw.arc([cx - 8, 14, cx + 8, 26], 0, 180, fill=1, width=1)
        draw.line([cx, 26, cx, 29], fill=1, width=1)
        draw.line([cx - 5, 29, cx + 5, 29], fill=1, width=1)

        for side in (-1, 1):
            for i in range(1, 4):
                amp = max(1, int(4 * abs(math.sin(t * 5 + i * 0.8))))
                bx = cx + side * (14 + i * 8)
                draw.line([bx, 16 - amp, bx, 16 + amp], fill=1, width=1)

        self._display(image)

    def _draw_alarm_flash(self, msg, tick):
        show_text = int(tick / 0.3) % 2 == 0

        image = self._new_frame()
        draw = ImageDraw.Draw(image)
        msg = self._fit_text(draw, str(msg or "ALERT"), font=self.font_cn)

        if show_text:
            self._draw_text_center(draw, 2, "!! WARNING !!", self.font_en)
            self._draw_text_center(draw, 18, msg, self.font_cn)
        else:
            draw.rectangle([0, 0, 127, 31], fill=1)
            self._draw_text_center_inv(draw, 2, "!! WARNING !!", self.font_en)
            self._draw_text_center_inv(draw, 18, msg, self.font_cn)

        self._display(image)

    _EVENT_DRAWERS = {
        "volume": "_draw_event_volume",
        "music": "_draw_event_music",
        "sensor": "_draw_event_sensor",
        "alert": "_draw_event_alert",
        "listening": "_draw_event_listening",
    }

    def _draw_event(self, ev):
        drawer = self._EVENT_DRAWERS.get(ev.kind)
        if drawer:
            getattr(self, drawer)(ev)
        else:
            self._draw_event_sensor(ev)

    def _run(self):
        tick = 0.0
        while not self.stop_event.is_set():
            try:
                # Priority: alarm > event > face_state
                with self.lock:
                    alarm = self.alarm
                    state = self.face_state

                if alarm:
                    self._draw_alarm_flash(alarm, tick)
                else:
                    ev = self._pop_event()
                    if ev:
                        self._draw_event(ev)
                    elif state == "tracking":
                        self._draw_face_tracking(tick)
                    elif state == "turning":
                        self._draw_face_turning(tick)
                    elif state == "sleeping":
                        self._draw_face_sleeping(tick)
                    else:
                        self._draw_face_idle(tick)
            except Exception as exc:
                now = time.monotonic()
                if now - self._last_draw_error_log_ts >= 5.0:
                    self._last_draw_error_log_ts = now
                    logger.error("[OLED] draw error: %s", exc)

            time.sleep(0.05)
            tick += 0.05

    def start(self):
        if not self.device:
            return
        self.stop_event.clear()
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def stop(self):
        self.stop_event.set()
