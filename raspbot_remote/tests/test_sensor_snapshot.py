#!/usr/bin/env python3
"""One-shot full sensor snapshot — verifies all sensors after assembly.

Usage:  python test_sensor_snapshot.py

Reads Ultrasonic, PCF8591, MPU6050, and Infrared all at once.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.ultrasonic import Ultrasonic
from modules.pcf8591 import PCF8591
from modules.mpu6050 import MPU6050
from modules.infrared import Infrared


def label(name, value, warn=False):
    return f"  {name:<14} {value}{'  <-- WARNING' if warn else ''}"


def main():
    print("=" * 64)
    print("Raspbot Sensor Snapshot")
    print("=" * 64)

    # Init all modules
    print("\n[Init]")
    us = Ultrasonic();        print("  Ultrasonic ...", "OK" if us.enabled else "N/A")
    adc = PCF8591();          print("  PCF8591 .....", "OK" if adc.enabled else "N/A")
    imu = MPU6050(auto_calibrate=True); print("  MPU6050 .....", "OK" if imu.enabled else "N/A")
    ir = Infrared();           print("  Infrared ....", "OK" if ir.enabled else "N/A")

    # Start
    for m in [us, adc, imu, ir]:
        if m.enabled:
            m.start()
    print("\nWaiting 3s for stabilisation...")
    time.sleep(3.0)

    # Read
    print("\n" + "=" * 64)
    print("READINGS")
    print("=" * 64)

    dist = us.get_distance();  w = dist <= 0 or dist >= 500
    print(f"\n[Ultrasonic]")
    print(label("Distance", f"{dist:.1f} cm", w))

    d = adc.get_data();  ok = d.get("pcf8591_ok", False)
    print(f"\n[PCF8591 {'OK' if ok else 'FAIL'}]")
    print(label("Light", f'raw={d.get("light",0):3d} lux={d.get("light_lux",0):4d}'))
    print(label("Temperature", f'raw={d.get("temp_raw",0):3d} {d.get("temp_c",0):.1f}C'))
    print(label("Smoke", f'{d.get("smoke",0):3d}% alarm={d.get("smoke_alarm",False)}'))
    print(label("Volume", f'{d.get("volume",0):3d}%'))

    imu_d = imu.get_data()
    print(f"\n[MPU6050 healthy={imu_d.get('healthy',False)} cal={imu_d.get('calibrated',False)}]")
    print(label("Roll/Pitch/Yaw", f'{imu_d.get("roll",0):+.1f}/{imu_d.get("pitch",0):+.1f}/{imu_d.get("yaw",0):+.1f} deg'))

    ir_d = ir.get_data();  track = ir_d.get("track", [1,1,1,1])
    print(f"\n[Infrared] track={track}")
    print(label("Cliff?", "YES" if all(int(v) == 0 for v in track[:4]) else "no"))

    # Stop
    print("\nShutting down...")
    for m in [us, adc, imu, ir]:
        if m.enabled:
            m.stop()
    print("Done.")


if __name__ == "__main__":
    main()
