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
        # YL-40 exposes the onboard thermistor through PCF8591, but the board
        # divider varies between clones. Use the field-calibrated linear model
        # by default; keep the physical NTC model available for lab calibration.
        self.adc_vref = float(os.getenv('RASPBOT_ADC_VREF', '5.0'))
        self.temp_model = os.getenv('RASPBOT_TEMP_MODEL', 'linear').strip().lower()
        self.temp_series_ohm = float(os.getenv('RASPBOT_TEMP_SERIES_OHM', '10000'))
        self.temp_nominal_ohm = float(os.getenv('RASPBOT_TEMP_NOMINAL_OHM', '10000'))
        self.temp_nominal_c = float(os.getenv('RASPBOT_TEMP_NOMINAL_C', '25.0'))
        self.temp_beta = float(os.getenv('RASPBOT_TEMP_BETA', '3950'))
        self.temp_divider = os.getenv('RASPBOT_TEMP_DIVIDER', 'direct').strip().lower()
        self.temp_room_c = float(os.getenv('RASPBOT_TEMP_ROOM_C', '21.0'))
        self.temp_adc_gain = float(os.getenv('RASPBOT_TEMP_ADC_GAIN', '-0.22'))
        self.temp_adc_bias = None
        preset_bias = os.getenv('RASPBOT_TEMP_ADC_BIAS', '').strip()
        if preset_bias:
            try:
                self.temp_adc_bias = float(preset_bias)
            except Exception:
                self.temp_adc_bias = None

        self.battery_divider_ratio = float(os.getenv('RASPBOT_BATTERY_DIVIDER_RATIO', '2.0'))
        self.battery_min_v = float(os.getenv('RASPBOT_BATTERY_MIN_V', '6.4'))
        self.battery_max_v = float(os.getenv('RASPBOT_BATTERY_MAX_V', '8.4'))
        print(
            '[PCF8591] temp model '
            f'{self.temp_model} divider={self.temp_divider} '
            f'ntc={self.temp_nominal_ohm:.0f} beta={self.temp_beta:.0f}'
        )
        print('[PCF8591] YL-40 channel map: AIN0=light AIN1=temp AIN2=aux/smoke AIN3=volume knob')
        print('[PCF8591] battery is command-line only; not sent in realtime env packets')

        self.lock = threading.Lock()
        self.bus_lock = threading.Lock()
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
            with self.bus_lock:
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

    def _temp_convert_linear(self, adc):
        if self.temp_adc_bias is None:
            self.temp_adc_bias = self.temp_room_c - (self.temp_adc_gain * float(adc))
            print(
                '[PCF8591] linear temp model initialized: '
                f'temp = {self.temp_adc_gain:.4f} * adc + {self.temp_adc_bias:.2f}'
            )
        temp_c = (self.temp_adc_gain * float(adc)) + self.temp_adc_bias
        temp_c = max(-20.0, min(80.0, temp_c))
        return round(temp_c, 1)

    def _temp_convert_ntc(self, adc):
        adc = int(max(1, min(254, int(adc))))
        if self.temp_divider == 'inverse':
            thermistor_ohm = self.temp_series_ohm * (255.0 - adc) / float(adc)
        else:
            thermistor_ohm = self.temp_series_ohm * float(adc) / (255.0 - adc)
        if thermistor_ohm <= 0 or self.temp_nominal_ohm <= 0 or self.temp_beta <= 0:
            return 0.0
        nominal_k = self.temp_nominal_c + 273.15
        temp_k = 1.0 / ((math.log(thermistor_ohm / self.temp_nominal_ohm) / self.temp_beta) + (1.0 / nominal_k))
        temp_c = max(-20.0, min(80.0, temp_k - 273.15))
        return round(temp_c, 1)

    def _temp_convert(self, adc):
        if self.temp_model == 'linear':
            return self._temp_convert_linear(adc)
        return self._temp_convert_ntc(adc)

    def _percent_convert(self, adc):
        return int(adc * 100 / 255)

    def _battery_convert(self, adc):
        voltage = (float(adc) * self.adc_vref / 255.0) * self.battery_divider_ratio
        span = max(0.1, self.battery_max_v - self.battery_min_v)
        percent = int(round((voltage - self.battery_min_v) * 100.0 / span))
        return round(voltage, 2), max(0, min(100, percent))

    def battery_health_from_adc(self, adc):
        voltage, percent = self._battery_convert(adc)
        if percent >= 35:
            status = 'OK'
        elif percent >= 15:
            status = 'LOW'
        else:
            status = 'CRITICAL'
        return {
            'raw': int(adc),
            'voltage': voltage,
            'percent': percent,
            'status': status,
        }

    def check_battery_health(self, channel=3, samples=8, delay=0.1):
        channel = int(max(0, min(3, int(channel))))
        samples = int(max(1, int(samples)))
        values = []
        for _ in range(samples):
            values.append(self._read(channel))
            time.sleep(float(delay))
        raw = int(round(sum(values) / len(values)))
        result = self.battery_health_from_adc(raw)
        result['channel'] = channel
        result['samples'] = values
        return result

    def _run(self):
        while not self.stop_event.is_set():
            channels = [self._read(ch) for ch in range(4)]
            light = channels[0]
            temp = channels[1]
            smoke = channels[2]
            volume_raw = channels[3]
            volume_percent = self._percent_convert(volume_raw)
            with self.lock:
                self.data = {
                    'light': light,
                    'light_lux': self._light_convert(light),
                    'temp_raw': temp,
                    'temp_c': self._temp_convert(temp),
                    'smoke': self._percent_convert(smoke),
                    'volume': volume_percent,
                    'volume_raw': volume_raw,
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
            with self.bus_lock:
                self.bus.close()
            self.bus = None
            self.enabled = False

    def get_data(self):
        with self.lock:
            return dict(self.data)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='PCF8591 sensor, YL-40 knob, and battery health tool')
    parser.add_argument('--battery-health', action='store_true', help='Read one ADC channel as battery divider input')
    parser.add_argument('--battery-channel', type=int, default=3, help='ADC channel used only for battery health check')
    parser.add_argument('--samples', type=int, default=8)
    parser.add_argument('--delay', type=float, default=0.1)
    args = parser.parse_args()

    sensor = PCF8591()
    if not sensor.enabled:
        print('ERROR')
        exit(1)
    if args.battery_health:
        try:
            result = sensor.check_battery_health(args.battery_channel, args.samples, args.delay)
            print(
                f"BATTERY {result['status']} "
                f"ch={result['channel']} raw={result['raw']} "
                f"voltage={result['voltage']:.2f}V percent={result['percent']}%"
            )
        finally:
            sensor.stop()
        exit(0)

    sensor.start()
    try:
        while True:
            d = sensor.get_data()
            print(
                f"L:{d['light']:3d}->{d['light_lux']:3d}lux "
                f"T:{d['temp_raw']:3d}->{d['temp_c']:5.1f}C "
                f"S:{d['smoke']:3d} VOL:{d['volume']:3d}%"
            )
            time.sleep(1)
    except KeyboardInterrupt:
        print('STOP')
    finally:
        sensor.stop()
