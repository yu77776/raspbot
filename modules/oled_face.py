#!/usr/bin/env python3
import time, threading, random
try:
    from luma.core.interface.serial import i2c as luma_i2c
    from luma.oled.device import ssd1306
    from PIL import Image, ImageDraw, ImageFont
    HAS_OLED = True
except Exception:
    HAS_OLED = False


class FaceEngine:
    def __init__(self):
        self.device = None
        self.font_cn = None
        self.font_en = None
        self.font_cn_name = 'unset'
        self.font_en_name = 'unset'
        self.state = 'env'
        self.alarm = ''
        self.env_data = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.eye_offset = 0

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

            print(f'[OLED] OK cn={self.font_cn_name} en={self.font_en_name}')
        except Exception as e:
            print(f'[OLED] FAIL: {e}')
            self.device = None

    def _load_font(self, candidates, size):
        for path in candidates:
            try:
                return ImageFont.truetype(path, size), path
            except Exception:
                continue
        return ImageFont.load_default(), 'PIL_default'

    def _draw_text_mixed(self, draw, pos, text):
        x, y = pos
        for ch in str(text):
            font = self.font_en if ord(ch) < 128 else self.font_cn
            draw.text((x, y), ch, font=font, fill=1)
            try:
                advance = draw.textlength(ch, font=font)
            except Exception:
                box = draw.textbbox((0, 0), ch, font=font)
                advance = (box[2] - box[0]) if box else 0
            x += max(1, int(round(advance)))

    def _draw_kv_row(self, draw, y, label, value, value_x=52):
        self._draw_text_mixed(draw, (2, y), label)
        self._draw_text_mixed(draw, (value_x, y), value)


    def set_state(self, s):
        with self.lock:
            self.state = s

    def set_alarm(self, msg):
        with self.lock:
            self.alarm = msg

    def set_pan(self, angle):
        self.eye_offset = int((angle - 90) / 45 * 9)
        self.eye_offset = max(-10, min(10, self.eye_offset))

    def set_env_data(self, data):
        with self.lock:
            self.env_data = data

    def _draw_eyes(self, ry):
        if not self.device:
            return
        img = Image.new('1', (128, 32), 0)
        draw = ImageDraw.Draw(img)
        lx = 38 + self.eye_offset
        rx = 90 + self.eye_offset
        draw.ellipse([lx - 14, 16 - ry, lx + 14, 16 + ry], fill=1)
        draw.ellipse([rx - 14, 16 - ry, rx + 14, 16 + ry], fill=1)
        self.device.display(img)

    def _draw_alarm(self, msg):
        if not self.device:
            return
        img = Image.new('1', (128, 32), 0)
        draw = ImageDraw.Draw(img)
        self._draw_text_mixed(draw, (10, 8), msg[:10])
        self.device.display(img)

    def _draw_env(self, page):
        if not self.device:
            return
        img = Image.new('1', (128, 32), 0)
        draw = ImageDraw.Draw(img)
        with self.lock:
            d = self.env_data

        y1, y2 = 0, 16

        if page == 0:
            t = d.get('temp_c', 0)
            l = d.get('light_lux', 0)
            self._draw_kv_row(draw, y1, '娓╁害: ', f'{t:.1f}C')
            self._draw_kv_row(draw, y2, '鍏夌収: ', f'{l}lux')
        elif page == 1:
            s = d.get('smoke', 0)
            dist = d.get('dist_cm', 0)
            self._draw_kv_row(draw, y1, '鐑熼浘: ', f'{s}')
            self._draw_kv_row(draw, y2, '璺濈: ', f'{dist:.0f}cm')
        else:
            v = d.get('volume', 0)
            self._draw_kv_row(draw, 9, '闊抽噺: ', f'{v}%')

        self.device.display(img)

    def _run(self):
        blink_t = 0
        next_blink = random.uniform(3, 5)
        ry = 10
        env_page = 0
        page_timer = 0

        while not self.stop_event.is_set():
            with self.lock:
                alarm = self.alarm
                state = self.state

            if alarm:
                self._draw_alarm(alarm)
            elif state == 'idle':
                blink_t += 0.05
                if blink_t >= next_blink:
                    ry = 0
                    blink_t = 0
                    next_blink = random.uniform(3, 5)
                else:
                    ry = 10
                self._draw_eyes(int(ry))
            elif state == 'env':
                page_timer += 0.1
                if page_timer >= 3:
                    env_page = (env_page + 1) % 3
                    page_timer = 0
                self._draw_env(env_page)

            time.sleep(0.05)

    def start(self):
        if not self.device:
            return
        self.stop_event.clear()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self.stop_event.set()

