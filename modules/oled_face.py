#!/usr/bin/env python3
import time, threading, random, math
try:
    from luma.core.interface.serial import i2c as luma_i2c
    from luma.oled.device import ssd1306
    from PIL import Image, ImageDraw, ImageFont
    HAS_OLED = True
except:
    HAS_OLED = False

class FaceEngine:
    def __init__(self):
        self.device = None
        self.font_cn = None
        self.font_en = None
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
            try:
                self.font_cn = ImageFont.truetype('/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf', 14)
                self.font_en = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 12)
            except:
                self.font_cn = ImageFont.load_default()
                self.font_en = ImageFont.load_default()
            print('[OLED] OK')
        except Exception as e:
            print(f'[OLED] FAIL: {e}')
            self.device = None
    
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
        if not self.device: return
        img = Image.new('1', (128, 32), 0)
        draw = ImageDraw.Draw(img)
        lx = 38 + self.eye_offset
        rx = 90 + self.eye_offset
        draw.ellipse([lx-14, 16-ry, lx+14, 16+ry], fill=1)
        draw.ellipse([rx-14, 16-ry, rx+14, 16+ry], fill=1)
        self.device.display(img)
    
    def _draw_alarm(self, msg):
        if not self.device: return
        img = Image.new('1', (128, 32), 0)
        draw = ImageDraw.Draw(img)
        draw.text((10, 8), msg[:10], font=self.font_cn, fill=1)
        self.device.display(img)
    
    def _draw_env(self, page):
        if not self.device: return
        img = Image.new('1', (128, 32), 0)
        draw = ImageDraw.Draw(img)
        with self.lock:
            d = self.env_data
        
        if page == 0:
            draw.text((5, 2), '温度: ', font=self.font_cn, fill=1)
            t = d.get('temp_c', 0)
            draw.text((45, 2), f'{t:.1f}C', font=self.font_en, fill=1)
            draw.text((5, 18), '光照: ', font=self.font_cn, fill=1)
            l = d.get('light_lux', 0)
            draw.text((45, 18), f'{l}lux', font=self.font_en, fill=1)
        elif page == 1:
            draw.text((5, 2), '烟雾: ', font=self.font_cn, fill=1)
            s = d.get('smoke', 0)
            draw.text((45, 2), f'{s}', font=self.font_en, fill=1)
            draw.text((5, 18), '距离: ', font=self.font_cn, fill=1)
            dist = d.get('dist_cm', 0)
            draw.text((45, 18), f'{dist:.0f}cm', font=self.font_en, fill=1)
        else:
            draw.text((5, 10), '音量: ', font=self.font_cn, fill=1)
            v = d.get('volume', 0)
            draw.text((45, 10), f'{v}%', font=self.font_en, fill=1)
        
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
        if not self.device: return
        self.stop_event.clear()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
    
    def stop(self):
        self.stop_event.set()
