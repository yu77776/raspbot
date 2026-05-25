#!/usr/bin/env python3
"""Measure HC-SR04 ultrasonic distance accuracy at fixed reference points.

Usage:  python test_ultrasonic_accuracy.py [--samples N] [--delay SEC]

Reference distances (cm): 10, 20, 30, 50, 100 (matching thesis Chapter 5).
"""

import argparse
import csv
import math
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.ultrasonic import Ultrasonic

REFERENCE_DISTANCES_CM = [10, 20, 30, 50, 100]


def build_parser():
    p = argparse.ArgumentParser(description="HC-SR04 ultrasonic distance accuracy test")
    p.add_argument("--samples", type=int, default=50, help="samples per reference distance")
    p.add_argument("--delay", type=float, default=0.06, help="delay between reads (s)")
    p.add_argument("--settle", type=float, default=1.2, help="settle time after repositioning (s)")
    p.add_argument("--output", type=str, default=None, help="CSV output path")
    p.add_argument("--trig", type=int, default=16, help="TRIG pin BOARD")
    p.add_argument("--echo", type=int, default=18, help="ECHO pin BOARD")
    return p


def collect_samples(sensor, n, delay):
    samples = []
    while len(samples) < n:
        d = sensor.get_distance()
        if 0.0 < d < 500.0:
            samples.append(d)
        time.sleep(delay)
    return samples


def main():
    args = build_parser().parse_args()

    print("=" * 76)
    print("HC-SR04 Ultrasonic Distance Accuracy Test")
    print(f"Reference: {REFERENCE_DISTANCES_CM} | Samples: {args.samples}")
    print(f"Pins: TRIG=BOARD.{args.trig}  ECHO=BOARD.{args.echo}")
    print("=" * 76)

    sensor = Ultrasonic(trig_pin=args.trig, echo_pin=args.echo)
    if not sensor.enabled:
        print("ERROR: sensor not available")
        sys.exit(1)

    sensor.start()
    print("Sensor started, waiting for valid readings...")
    for _ in range(20):
        d = sensor.get_distance()
        if 0.0 < d < 500.0:
            break
        time.sleep(0.15)

    results = []
    for ref_cm in REFERENCE_DISTANCES_CM:
        print(f"\n--- Reference: {ref_cm} cm ---")
        input(f"Place obstacle at {ref_cm} cm and press Enter...")
        time.sleep(args.settle)

        samples = collect_samples(sensor, args.samples, args.delay)
        n = len(samples)
        mean_d = sum(samples) / n
        errors = [s - ref_cm for s in samples]
        mean_error = sum(errors) / n
        error_rate = abs(mean_error) / ref_cm * 100.0
        variance = sum((s - mean_d) ** 2 for s in samples) / (n - 1) if n > 1 else 0.0
        std_d = math.sqrt(variance)
        max_error = max(abs(e) for e in errors)

        results.append({
            "ref_cm": ref_cm, "samples": n, "mean_cm": round(mean_d, 2),
            "mean_error_cm": round(mean_error, 2), "error_rate_pct": round(error_rate, 2),
            "std_cm": round(std_d, 2), "max_error_cm": round(max_error, 2),
        })
        print(f"  Mean: {mean_d:.1f} cm  Error: {mean_error:+.1f} cm ({error_rate:.1f}%)  Std: {std_d:.1f}")

    sensor.stop()

    # Summary table
    print("\n" + "=" * 76)
    print(f'{"Ref":>7}  {"N":>3}  {"Mean":>8}  {"Error":>8}  {"Err%":>6}  {"Std":>7}  {"MaxErr":>8}')
    print("-" * 76)
    for r in results:
        print(f'{r["ref_cm"]:>7}  {r["samples"]:>3}  {r["mean_cm"]:>8.1f}  '
              f'{r["mean_error_cm"]:>+8.1f}  {r["error_rate_pct"]:>5.1f}%  '
              f'{r["std_cm"]:>7.1f}  {r["max_error_cm"]:>8.1f}')

    # CSV output
    csv_path = args.output or f"ultrasonic_accuracy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)) or ".", csv_path)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"\nSaved: {csv_path}")


if __name__ == "__main__":
    main()
