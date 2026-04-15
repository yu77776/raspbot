#!/usr/bin/env python3

import math
import os
import threading
import time

try:
    import smbus2
    HAS_I2C = True
except Exception:
    HAS_I2C = False


class PCF8591:
    def __init__(self, addr=0x48, smoke_threshold=100):
        self.addr = addr
        self.threshold = smoke_threshold
        self.data = {
            'light': 0,
            'light_lux': 0,
            'temp_raw': 0,
            'temp_c': 0,
            'smoke': 0,
            'volume': 0,
            'smoke_alarm': False,
        }
        # One-point temperature calibration:
        # current ambient is mapped to target temperature (default 21C).
        self.temp_cal_target_c = float(os.getenv('RASPBOT_TEMP_CAL_TARGET_C', '21.0'))
        self.temp_cal_slope_c_per_adc = float(os.getenv('RASPBOT_TEMP_CAL_SLOPE', '-0.22'))
        self.temp_cal_anchor_adc = None
        preset_anchor = os.getenv('RASPBOT_TEMP_CAL_ANCHOR_ADC', '').strip()
        if preset_anchor:
            try:
                self.temp_cal_anchor_adc = float(preset_anchor)
            except Exception:
                self.temp_cal_anchor_adc = None

        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.bus = None
        self.enabled = False
        self.thread = None
        self.started = False
        if HAS_I2C:
            try:
                self.bus = smbus2.SMBus(1)
                self.enabled = True
                print('[PCF8591] OK')
            except Exception as e:
                print(f'[PCF8591] FAIL: {e}')

    def _read(self, ch):
        try:
            self.bus.write_byte(self.addr, 0x40 | ch)
            self.bus.read_byte(self.addr)
            return self.bus.read_byte(self.addr)
        except Exception:
            return 0

    def _light_convert(self, adc):
        if adc == 0:
            return 0
        v = adc * 5.0 / 255.0
        if v >= 5.0:
            return 0
        rs = 10000 * v / (5.0 - v)
        if rs > 1000000:
            return 0
        if rs < 5000:
            return 1000
        return round(10 ** ((math.log10(rs) - 6) * (-1)))

    def _temp_convert(self, adc):
        if self.temp_cal_anchor_adc is None:
            self.temp_cal_anchor_adc = float(adc)
            print(
                '[PCF8591] temp calibration anchor set: '
                f'adc={adc} -> {self.temp_cal_target_c:.1f}C'
            )
        temp_c = self.temp_cal_target_c + (
            (float(adc) - self.temp_cal_anchor_adc) * self.temp_cal_slope_c_per_adc
        )
        temp_c = max(-20.0, min(80.0, temp_c))
        return round(temp_c, 1)

    def _percent_convert(self, adc):
        return int(adc * 100 / 255)

    def _run(self):
        while not self.stop_event.is_set():
            light = self._read(0)
            temp = self._read(1)
            smoke = self._read(2)
            voltage = self._read(3)
            with self.lock:
                self.data = {
                    'light': light,
                    'light_lux': self._light_convert(light),
                    'temp_raw': temp,
                    'temp_c': self._temp_convert(temp),
                    'smoke': self._percent_convert(smoke),
                    'volume': self._percent_convert(voltage),
                    'smoke_alarm': smoke > self.threshold,
                }
            time.sleep(0.5)

    def start(self):
        if not self.enabled and HAS_I2C:
            try:
                self.bus = smbus2.SMBus(1)
                self.enabled = True
            except Exception as e:
                print(f'[PCF8591] FAIL: {e}')
                self.enabled = False
        if not self.enabled:
            return
        if self.started and self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.started = True

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.started = False
        if self.bus:
            self.bus.close()
            self.bus = None
            self.enabled = False

    def get_data(self):
        with self.lock:
            return dict(self.data)


if __name__ == '__main__':
    sensor = PCF8591()
    if not sensor.enabled:
        print('ERROR')
        exit(1)
    sensor.start()
    try:
        while True:
            d = sensor.get_data()
            print(
                f"L:{d['light']:3d}->{d['light_lux']:3d}lux "
                f"T:{d['temp_raw']:3d}->{d['temp_c']:5.1f}C "
                f"S:{d['smoke']:3d} V:{d['volume']:.2f}%"
            )
            time.sleep(1)
    except KeyboardInterrupt:
        print('STOP')
    finally:
        sensor.stop()
