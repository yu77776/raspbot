#!/usr/bin/env python3
"""
OLED face engine for SSD1306 128x32.

Audience: babies (expression-first), not operators.
Render priority: alarm > event > face_state.
"""

import math
import random
import threading
import time

from logger_setup import setup_logger

logger = setup_logger('raspbot.oled')

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

        self.face_state = "idle"  # idle | tracking | searching | sleeping
        self.mode_label = "AUTO"
        self.alarm = ""
        self.env_data = {}
        self.eye_offset = 0
        self._searching_since = None  # auto-transition to sleeping after timeout

        self._event = None
        self._event_lock = threading.Lock()

        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self._running = False
        self._thread = None
        self._last_draw_error_log_ts = 0.0
        now = time.monotonic()
        self._blink_close_until = 0.0
        self._next_blink_at = now + random.uniform(4.5, 5.5)

        if not HAS_OLED:
            logger.warning("unavailable")
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

            logger.info("OK cn=%s en=%s", self.font_cn_name, self.font_en_name)
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

    def _clear_display(self):
        if self.device:
            self.device.display(self._new_frame())

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

    def _repair_mojibake(self, text):
        value = str(text or "")
        if not value:
            return ""
        if any("\u4e00" <= ch <= "\u9fff" for ch in value):
            return value
        suspicious = sum(1 for ch in value if ch in "ÃÂâ€çéèåæäöüïðñ")
        if suspicious <= 0:
            return value
        for encoding in ("latin1", "cp1252"):
            try:
                repaired = value.encode(encoding).decode("utf-8")
            except Exception:
                continue
            if any("\u4e00" <= ch <= "\u9fff" for ch in repaired):
                return repaired
        return value

    def _sanitize_alarm_text(self, text):
        cleaned = []
        for ch in str(text or ""):
            if ch == "°":
                continue
            if ch == "±":
                cleaned.append("+/-")
                continue
            if ord(ch) < 128 and (ch.isalnum() or ch in " .:/_+-"):
                cleaned.append(ch)
        return " ".join("".join(cleaned).split()) or "ALERT"

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

    def set_mode(self, mode):
        label = "AUTO" if str(mode or "").strip().lower() in {"auto", "tracking", "app_auto"} else "MANUAL"
        with self.lock:
            self.mode_label = label

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

    def clear_event(self, kind=None):
        with self._event_lock:
            if self._event is None:
                return
            if kind is None or self._event.kind == str(kind):
                self._event = None

    def _draw_mode_badge(self, draw):
        with self.lock:
            label = self.mode_label
        if not label:
            return
        text = "A" if label == "AUTO" else "M"
        draw.rectangle([0, 0, 12, 8], outline=1)
        draw.text((4, 0), text, font=self.font_en, fill=1)

    # Event queue
    def _pop_event(self):
        with self._event_lock:
            ev = self._event
            if ev and ev.expired:
                self._event = None
                return None
            return ev

    def _event_overlays_alarm(self, ev):
        return bool(ev and ev.kind == "volume")  # volume composites with alarm

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
        self._draw_mode_badge(draw)
        self._display(image)

    def _draw_face_tracking(self, tick):
        del tick
        image = self._new_frame()
        draw = ImageDraw.Draw(image)
        with self.lock:
            offset = self.eye_offset
        lx, rx = 38 + offset, 90 + offset
        # Solid round eyes — happy, locked on target.
        draw.ellipse([lx - 14, 6, lx + 14, 26], fill=1)
        draw.ellipse([rx - 14, 6, rx + 14, 26], fill=1)
        self._draw_mode_badge(draw)
        self._display(image)

    def _draw_face_searching(self, tick):
        del tick
        image = self._new_frame()
        draw = ImageDraw.Draw(image)
        with self.lock:
            offset = self.eye_offset
        lx, rx = 38 + offset, 90 + offset
        # Hollow eyes — pupil follows actual pan servo, scanning for baby.
        draw.ellipse([lx - 14, 6, lx + 14, 26], outline=1, width=1)
        draw.ellipse([rx - 14, 6, rx + 14, 26], outline=1, width=1)
        pupil = offset // 2
        draw.ellipse([lx - 4 + pupil, 11, lx + 4 + pupil, 21], fill=1)
        draw.ellipse([rx - 4 + pupil, 11, rx + 4 + pupil, 21], fill=1)
        self._draw_mode_badge(draw)
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

        # Compact layout for 128x32: title + bar + pct, vertically stacked.
        self._draw_text_center(draw, 0, "VOL", self.font_en)

        bar_x, bar_y, bar_w, bar_h = 14, 9, 100, 7
        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=1)
        fill_w = int(bar_w * vol / 100)
        if fill_w > 0:
            draw.rectangle([bar_x + 1, bar_y + 1, bar_x + fill_w, bar_y + bar_h - 1], fill=1)

        pct_text = f"{vol}%"
        tw = self._text_width_mixed(draw, pct_text, self.font_en)
        x = max(0, (128 - tw) // 2)
        self._draw_text_mixed(draw, x, 17, pct_text, font=self.font_en, fill=1)
        self._display(image)

    def _draw_note(self, draw, cx, cy):
        draw.ellipse([cx - 3, cy, cx + 3, cy + 4], fill=1)
        draw.line([cx + 3, cy + 2, cx + 3, cy - 10], fill=1, width=1)
        draw.line([cx + 3, cy - 10, cx + 7, cy - 7], fill=1, width=1)

    def _draw_event_music(self, ev):
        image = self._new_frame()
        draw = ImageDraw.Draw(image)
        t = ev.elapsed

        for i in range(4):
            x = 18 + i * 30
            y = 8 + int(3 * math.sin(t * 4 + i * 1.4))
            self._draw_note(draw, x, y)

        value = ev.value if isinstance(ev.value, dict) else {}
        name = self._repair_mojibake(value.get("name", "") if value else ev.value or "")
        if name:
            max_width = 124
            text_font = self.font_cn if any(ord(ch) > 127 for ch in name) else self.font_en
            if self._text_width_mixed(draw, name, text_font) <= max_width:
                visible = name
            else:
                padded = f"{name}   "
                start = int(t * 2.5) % max(1, len(padded))
                rotated = padded[start:] + padded[:start]
                visible = self._fit_text(draw, rotated, max_width=max_width, font=text_font)
            self._draw_text_center(draw, 20, visible, text_font)

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
        self._draw_alarm_flash(str(ev.value or "ALERT"), ev.elapsed)

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

    def _draw_alarm_with_volume(self, alarm_msg, tick, ev):
        """Composite: slim alarm banner at top, volume bar below."""
        image = self._new_frame()
        draw = ImageDraw.Draw(image)

        # Top 8px: compact alarm indicator — flash on/off
        show = int(tick / 0.3) % 2 == 0
        msg = self._fit_text(draw, self._sanitize_alarm_text(alarm_msg), font=self.font_en)
        if show:
            self._draw_text_center(draw, 0, f"! {msg}", self.font_en)
        else:
            draw.rectangle([0, 0, 127, 8], fill=1)
            self._draw_text_center_inv(draw, 0, f"! {msg}", self.font_en)

        # Bottom: slim volume bar, no percentage to keep alarm readable
        vol = int(ev.value or 0)
        vol = max(0, min(100, vol))
        bar_x, bar_y, bar_w, bar_h = 14, 13, 100, 7
        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=1)
        fill_w = int(bar_w * vol / 100)
        if fill_w > 0:
            draw.rectangle([bar_x + 1, bar_y + 1, bar_x + fill_w, bar_y + bar_h - 1], fill=1)

        self._display(image)

    def _draw_alarm_flash(self, msg, elapsed):
        show_text = int(elapsed / 0.3) % 2 == 0
        image = self._new_frame()
        draw = ImageDraw.Draw(image)
        msg = self._fit_text(draw, self._sanitize_alarm_text(msg), font=self.font_en)
        if show_text:
            self._draw_text_center(draw, 2, "!! WARNING !!", self.font_en)
            self._draw_text_center(draw, 18, msg, self.font_en)
        else:
            draw.rectangle([0, 0, 127, 31], fill=1)
            self._draw_text_center_inv(draw, 2, "!! WARNING !!", self.font_en)
            self._draw_text_center_inv(draw, 18, msg, self.font_en)
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
        SEARCH_TIMEOUT = 20.0
        while not self.stop_event.is_set():
            try:
                with self.lock:
                    alarm = self.alarm
                    state = self.face_state

                # Auto-transition: searching too long → sleeping
                if state == "searching":
                    if self._searching_since is None:
                        self._searching_since = time.monotonic()
                    elif time.monotonic() - self._searching_since > SEARCH_TIMEOUT:
                        state = "sleeping"
                else:
                    self._searching_since = None

                ev = self._pop_event()
                if alarm and ev and ev.kind == "volume":
                    self._draw_alarm_with_volume(alarm, tick, ev)
                elif alarm:
                    self._draw_alarm_flash(alarm, tick)
                else:
                    if ev:
                        self._draw_event(ev)
                    elif state == "tracking":
                        self._draw_face_tracking(tick)
                    elif state == "searching":
                        self._draw_face_searching(tick)
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
            tick = (tick + 0.05) % (2 * math.pi / 0.05)
        self._running = False

    def start(self):
        if not self.device:
            return
        if self._running:
            return
        self.stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._clear_display()
