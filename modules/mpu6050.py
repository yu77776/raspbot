#!/usr/bin/env python3
"""MPU6050 IMU module with Madgwick quaternion fusion."""
import math
import threading
import time
from collections import deque

try:
    import smbus2
    HAS_I2C = True
except Exception:
    smbus2 = None
    HAS_I2C = False


class MPU6050:
    REG_SMPLRT_DIV = 0x19
    REG_CONFIG = 0x1A
    REG_GYRO_CONFIG = 0x1B
    REG_ACCEL_CONFIG = 0x1C
    REG_PWR_MGMT_1 = 0x6B
    REG_ACCEL_XOUT_H = 0x3B

    def __init__(
        self,
        addr=0x68,
        bus_id=1,
        sample_hz=100.0,
        beta=0.08,
        auto_calibrate=True,
        calibrate_timeout=20.0,
        calibrate_window=2.5,
    ):
        self.addr = int(addr)
        self.bus_id = int(bus_id)
        self.sample_hz = float(sample_hz)
        self.sample_dt = 1.0 / max(5.0, self.sample_hz)
        self.beta = float(beta)
        self.auto_calibrate = bool(auto_calibrate)
        self.calibrate_timeout = float(calibrate_timeout)
        self.calibrate_window = float(calibrate_window)

        self.bus = None
        self.enabled = False
        self.started = False
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

        self.q = [1.0, 0.0, 0.0, 0.0]  # w, x, y, z
        self.gyro_bias_dps = [0.0, 0.0, 0.0]
        self.accel_bias_g = [0.0, 0.0, 0.0]
        self.calibrated = False
        self.last_ok_ts = 0.0
        self.last_error = ''

        self.data = {
            'roll': 0.0,
            'pitch': 0.0,
            'yaw': 0.0,
            'quat': [1.0, 0.0, 0.0, 0.0],
            'gyro_dps': [0.0, 0.0, 0.0],
            'accel_g': [0.0, 0.0, 0.0],
            'calibrated': False,
            'healthy': False,
            'last_ok_ts': 0.0,
        }

        self._open()

    def _open(self):
        if not HAS_I2C:
            print('[IMU] smbus2 missing, disabled')
            return
        try:
            self.bus = smbus2.SMBus(self.bus_id)
            self._init_chip()
            self.enabled = True
            print(f'[IMU] init ok addr=0x{self.addr:02X} bus={self.bus_id}')
        except Exception as e:
            self.enabled = False
            self.bus = None
            print(f'[IMU] init fail: {e}')

    def _init_chip(self):
        # Wake chip, 1kHz/(1+9)=100Hz, low-pass ~42Hz, gyro +/-250dps, accel +/-2g
        self._write_u8(self.REG_PWR_MGMT_1, 0x00)
        time.sleep(0.08)
        self._write_u8(self.REG_SMPLRT_DIV, 0x09)
        self._write_u8(self.REG_CONFIG, 0x03)
        self._write_u8(self.REG_GYRO_CONFIG, 0x00)
        self._write_u8(self.REG_ACCEL_CONFIG, 0x00)

    def _write_u8(self, reg, val):
        self.bus.write_byte_data(self.addr, reg, val & 0xFF)

    def _read_block(self, reg, n):
        return self.bus.read_i2c_block_data(self.addr, reg, n)

    @staticmethod
    def _to_i16(hi, lo):
        v = (hi << 8) | lo
        return v - 65536 if v > 32767 else v

    def _read_raw(self):
        b = self._read_block(self.REG_ACCEL_XOUT_H, 14)
        ax = self._to_i16(b[0], b[1])
        ay = self._to_i16(b[2], b[3])
        az = self._to_i16(b[4], b[5])
        temp = self._to_i16(b[6], b[7])
        gx = self._to_i16(b[8], b[9])
        gy = self._to_i16(b[10], b[11])
        gz = self._to_i16(b[12], b[13])
        return ax, ay, az, temp, gx, gy, gz

    def _read_units(self):
        ax, ay, az, _t, gx, gy, gz = self._read_raw()
        # +/-2g => 16384 LSB/g ; +/-250dps => 131 LSB/(deg/s)
        return {
            'ax_g': ax / 16384.0,
            'ay_g': ay / 16384.0,
            'az_g': az / 16384.0,
            'gx_dps': gx / 131.0,
            'gy_dps': gy / 131.0,
            'gz_dps': gz / 131.0,
        }

    @staticmethod
    def _mean(vals):
        return sum(vals) / max(1, len(vals))

    @classmethod
    def _std(cls, vals):
        if not vals:
            return 0.0
        m = cls._mean(vals)
        return math.sqrt(sum((x - m) * (x - m) for x in vals) / len(vals))

    def _window_is_still_flat(self, samples):
        axs = [s['ax_g'] for s in samples]
        ays = [s['ay_g'] for s in samples]
        azs = [s['az_g'] for s in samples]
        gxs = [s['gx_dps'] for s in samples]
        gys = [s['gy_dps'] for s in samples]
        gzs = [s['gz_dps'] for s in samples]

        acc_mag = [math.sqrt(x * x + y * y + z * z) for x, y, z in zip(axs, ays, azs)]
        acc_mag_mean = self._mean(acc_mag)
        acc_mag_std = self._std(acc_mag)
        gx_std = self._std(gxs)
        gy_std = self._std(gys)
        gz_std = self._std(gzs)

        ax_mean = self._mean(axs)
        ay_mean = self._mean(ays)
        az_mean = self._mean(azs)

        still_ok = gx_std < 0.8 and gy_std < 0.8 and gz_std < 0.8 and acc_mag_std < 0.03
        flat_ok = abs(ax_mean) < 0.12 and abs(ay_mean) < 0.12 and abs(abs(az_mean) - 1.0) < 0.12
        norm_ok = abs(acc_mag_mean - 1.0) < 0.12
        return still_ok and flat_ok and norm_ok

    def _collect_window(self, timeout_s):
        n = max(20, int(self.sample_hz * self.calibrate_window))
        buf = deque(maxlen=n)
        t0 = time.monotonic()
        dt = 1.0 / max(20.0, self.sample_hz)
        while time.monotonic() - t0 < timeout_s:
            try:
                buf.append(self._read_units())
                if len(buf) >= n and self._window_is_still_flat(buf):
                    return list(buf), True
            except Exception:
                pass
            time.sleep(dt)
        return list(buf), False

    @staticmethod
    def _quat_from_rpy(roll, pitch, yaw):
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)
        w = cr * cp * cy + sr * sp * sy
        x = sr * cp * cy - cr * sp * sy
        y = cr * sp * cy + sr * cp * sy
        z = cr * cp * sy - sr * sp * cy
        return [w, x, y, z]

    def calibrate(self, timeout_s=None):
        if not self.enabled:
            return False
        timeout_s = self.calibrate_timeout if timeout_s is None else float(timeout_s)
        print('[IMU] keep still and flat for auto calibration...')
        samples, ok = self._collect_window(timeout_s)
        if not samples:
            print('[IMU] calibration failed: no samples')
            return False

        mean_ax = self._mean([s['ax_g'] for s in samples])
        mean_ay = self._mean([s['ay_g'] for s in samples])
        mean_az = self._mean([s['az_g'] for s in samples])
        mean_gx = self._mean([s['gx_dps'] for s in samples])
        mean_gy = self._mean([s['gy_dps'] for s in samples])
        mean_gz = self._mean([s['gz_dps'] for s in samples])

        z_ref = 1.0 if mean_az >= 0 else -1.0
        self.accel_bias_g = [mean_ax, mean_ay, mean_az - z_ref]
        self.gyro_bias_dps = [mean_gx, mean_gy, mean_gz]

        # Initialize attitude from calibrated gravity vector.
        ax0 = mean_ax - self.accel_bias_g[0]
        ay0 = mean_ay - self.accel_bias_g[1]
        az0 = mean_az - self.accel_bias_g[2]
        roll0 = math.atan2(ay0, az0)
        pitch0 = math.atan2(-ax0, math.sqrt(ay0 * ay0 + az0 * az0))
        self.q = self._quat_from_rpy(roll0, pitch0, 0.0)

        self.calibrated = True
        state = 'ok' if ok else 'timeout(use latest window)'
        print(
            f'[IMU] calibration {state} '
            f'gyro_bias(dps)=({mean_gx:.3f},{mean_gy:.3f},{mean_gz:.3f}) '
            f'acc_bias(g)=({self.accel_bias_g[0]:.4f},{self.accel_bias_g[1]:.4f},{self.accel_bias_g[2]:.4f})'
        )
        return ok

    def _madgwick_update_imu(self, gx, gy, gz, ax, ay, az, dt):
        q0, q1, q2, q3 = self.q

        norm_a = math.sqrt(ax * ax + ay * ay + az * az)
        if norm_a > 1e-9:
            ax /= norm_a
            ay /= norm_a
            az /= norm_a

            f1 = 2.0 * (q1 * q3 - q0 * q2) - ax
            f2 = 2.0 * (q0 * q1 + q2 * q3) - ay
            f3 = 2.0 * (0.5 - q1 * q1 - q2 * q2) - az

            s0 = -2.0 * q2 * f1 + 2.0 * q1 * f2
            s1 = 2.0 * q3 * f1 + 2.0 * q0 * f2 - 4.0 * q1 * f3
            s2 = -2.0 * q0 * f1 + 2.0 * q3 * f2 - 4.0 * q2 * f3
            s3 = 2.0 * q1 * f1 + 2.0 * q2 * f2
            norm_s = math.sqrt(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3)
            if norm_s > 1e-9:
                s0 /= norm_s
                s1 /= norm_s
                s2 /= norm_s
                s3 /= norm_s
            else:
                s0 = s1 = s2 = s3 = 0.0
        else:
            s0 = s1 = s2 = s3 = 0.0

        q_dot0 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz) - self.beta * s0
        q_dot1 = 0.5 * (q0 * gx + q2 * gz - q3 * gy) - self.beta * s1
        q_dot2 = 0.5 * (q0 * gy - q1 * gz + q3 * gx) - self.beta * s2
        q_dot3 = 0.5 * (q0 * gz + q1 * gy - q2 * gx) - self.beta * s3

        q0 += q_dot0 * dt
        q1 += q_dot1 * dt
        q2 += q_dot2 * dt
        q3 += q_dot3 * dt

        norm_q = math.sqrt(q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3)
        if norm_q > 1e-9:
            self.q = [q0 / norm_q, q1 / norm_q, q2 / norm_q, q3 / norm_q]

    def _quat_to_euler_deg(self):
        q0, q1, q2, q3 = self.q
        roll = math.atan2(2.0 * (q0 * q1 + q2 * q3), 1.0 - 2.0 * (q1 * q1 + q2 * q2))
        sinp = 2.0 * (q0 * q2 - q3 * q1)
        sinp = max(-1.0, min(1.0, sinp))
        pitch = math.asin(sinp)
        yaw = math.atan2(2.0 * (q0 * q3 + q1 * q2), 1.0 - 2.0 * (q2 * q2 + q3 * q3))
        return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)

    def _run(self):
        error_count = 0
        prev_t = time.monotonic()
        while not self.stop_event.is_set():
            t0 = time.monotonic()
            dt = t0 - prev_t
            prev_t = t0
            dt = max(0.002, min(0.05, dt))
            try:
                u = self._read_units()
                ax = u['ax_g'] - self.accel_bias_g[0]
                ay = u['ay_g'] - self.accel_bias_g[1]
                az = u['az_g'] - self.accel_bias_g[2]
                gx_dps = u['gx_dps'] - self.gyro_bias_dps[0]
                gy_dps = u['gy_dps'] - self.gyro_bias_dps[1]
                gz_dps = u['gz_dps'] - self.gyro_bias_dps[2]

                self._madgwick_update_imu(
                    math.radians(gx_dps),
                    math.radians(gy_dps),
                    math.radians(gz_dps),
                    ax, ay, az, dt
                )
                roll, pitch, yaw = self._quat_to_euler_deg()

                with self.lock:
                    self.last_ok_ts = time.time()
                    self.data = {
                        'roll': round(roll, 2),
                        'pitch': round(pitch, 2),
                        'yaw': round(yaw, 2),
                        'quat': [round(v, 6) for v in self.q],
                        'gyro_dps': [round(gx_dps, 4), round(gy_dps, 4), round(gz_dps, 4)],
                        'accel_g': [round(ax, 5), round(ay, 5), round(az, 5)],
                        'calibrated': self.calibrated,
                        'healthy': True,
                        'last_ok_ts': self.last_ok_ts,
                    }
                    self.last_error = ''
                error_count = 0
            except Exception as e:
                error_count += 1
                with self.lock:
                    self.last_error = str(e)
                    self.data['healthy'] = False
                if error_count == 1 or error_count % 20 == 0:
                    print(f'[IMU] read/update error: {e}')

            spend = time.monotonic() - t0
            time.sleep(max(0.0, self.sample_dt - spend))

    def start(self):
        if not self.enabled and HAS_I2C:
            self._open()
        if not self.enabled:
            return
        if self.started and self.thread and self.thread.is_alive():
            return
        if self.auto_calibrate and not self.calibrated:
            self.calibrate(self.calibrate_timeout)
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.started = True

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        self.started = False

    def get_data(self):
        with self.lock:
            return dict(self.data)

    def get_euler(self):
        d = self.get_data()
        return d.get('roll', 0.0), d.get('pitch', 0.0), d.get('yaw', 0.0)

    def get_quaternion(self):
        d = self.get_data()
        return list(d.get('quat', [1.0, 0.0, 0.0, 0.0]))

    def is_healthy(self, timeout_s=1.0):
        with self.lock:
            ts = self.last_ok_ts
        return ts > 0 and (time.time() - ts) <= float(timeout_s)


if __name__ == '__main__':
    imu = MPU6050(addr=0x68, sample_hz=100, beta=0.08, auto_calibrate=True)
    if not imu.enabled:
        print('[IMU] not enabled')
    else:
        imu.start()
        try:
            while True:
                d = imu.get_data()
                print(
                    f"Roll={d['roll']:7.2f}  Pitch={d['pitch']:7.2f}  Yaw={d['yaw']:7.2f}  "
                    f"healthy={d['healthy']} calibrated={d['calibrated']}"
                )
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            imu.stop()
