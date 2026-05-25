#!/usr/bin/env python3
"""Measure PCF8591 NTC temperature accuracy against a reference thermometer.

Usage:  python test_temperature_accuracy.py [--samples N]

Reads the NTC thermistor via PCF8591 AIN1, computes temperature with B-value
model, and asks operator to enter reference thermometer reading for comparison.
"""

import argparse
import csv
import math
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.pcf8591 import PCF8591


def build_parser():
    p = argparse.ArgumentParser(description="PCF8591 NTC temperature accuracy test")
    p.add_argument("--samples", type=int, default=30, help="ADC reads per trial")
    p.add_argument("--delay", type=float, default=0.1, help="delay between reads (s)")
    p.add_argument("--channel", type=int, default=1, help="ADC channel (AIN1=1)")
    p.add_argument("--output", type=str, default=None, help="CSV output path")
    return p


def main():
    args = build_parser().parse_args()

    print("=" * 64)
    print("PCF8591 NTC Temperature Accuracy Test")
    print(f"Channel: AIN{args.channel} | Samples: {args.samples}")
    print("=" * 64)

    sensor = PCF8591()
    if not sensor.enabled:
        print("ERROR: PCF8591 not available")
        sys.exit(1)

    print(f"Vref={sensor.adc_vref}V Rfix={sensor.temp_series_ohm}ohm "
          f"R0={sensor.temp_nominal_ohm}ohm T0={sensor.temp_nominal_c}C Beta={sensor.temp_beta}")
    print("\nEnter reference temperature (C), or blank to finish.\n")

    results = []
    trial = 0
    try:
        while True:
            trial += 1
            ref = input(f"Trial {trial} - Reference temp (C): ").strip()
            if not ref:
                trial -= 1
                break
            try:
                ref_temp = float(ref)
            except ValueError:
                print("  Invalid, retry.\n")
                trial -= 1
                continue

            diag = sensor.check_temp_diagnostics(channel=args.channel, samples=args.samples, delay=args.delay)
            measured_c = diag["temp_c"]
            error_c = round(measured_c - ref_temp, 1)
            error_rate = round(abs(error_c) / max(0.1, abs(ref_temp)) * 100.0, 1)

            results.append({"trial": trial, "ref_c": ref_temp, "measured_c": measured_c,
                           "error_c": error_c, "error_rate_pct": error_rate,
                           "raw_adc": diag["raw"], "thermistor_ohm": diag["thermistor_ohm"]})
            print(f"  Ref: {ref_temp:.1f}C  Meas: {measured_c:.1f}C  "
                  f"Error: {error_c:+.1f}C ({error_rate}%)  ADC: {diag['raw']}\n")

    except KeyboardInterrupt:
        print("\nInterrupted.\n")
    finally:
        sensor.stop()

    if not results:
        return

    errors = [r["error_c"] for r in results]
    abs_errors = [abs(e) for e in errors]
    mean_abs = sum(abs_errors) / len(abs_errors)
    max_abs = max(abs_errors)
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors))

    print("=" * 64)
    print(f'{"Trial":>5}  {"Ref":>7}  {"Meas":>7}  {"Error":>7}  {"Err%":>6}  {"ADC":>5}')
    print("-" * 64)
    for r in results:
        print(f'{r["trial"]:>5}  {r["ref_c"]:>7.1f}  {r["measured_c"]:>7.1f}  '
              f'{r["error_c"]:>+7.1f}  {r["error_rate_pct"]:>5.1f}%  {r["raw_adc"]:>5}')
    print(f"\nMeanAbsErr={mean_abs:.1f}C  MaxAbsErr={max_abs:.1f}C  RMSE={rmse:.1f}C  N={len(results)}")

    csv_path = args.output or f"temperature_accuracy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)) or ".", csv_path)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"Saved: {csv_path}")


if __name__ == "__main__":
    main()
