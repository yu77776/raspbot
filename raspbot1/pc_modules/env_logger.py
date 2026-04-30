"""CSV environment logger."""
import csv
import os
import time

from .settings import BASE_DIR

LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

_csv_path = os.path.join(LOG_DIR, 'env_log.csv')
_csv_headers = [
    'timestamp', 'light', 'light_lux', 'temp_c', 'smoke',
    'volume', 'crying', 'cry_score', 'dist_cm', 'track', 'alarm',
    'imu_yaw', 'imu_roll', 'imu_pitch', 'fps',
]
_csv_buffer = []
_csv_last_flush = 0.0
_CSV_FLUSH_COUNT = 10
_CSV_FLUSH_SECS = 5.0


def _ensure_csv():
    if not os.path.exists(_csv_path):
        with open(_csv_path, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(_csv_headers)


def flush_csv():
    global _csv_buffer, _csv_last_flush
    if not _csv_buffer:
        return
    _ensure_csv()
    with open(_csv_path, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows(_csv_buffer)
    _csv_buffer = []
    _csv_last_flush = time.monotonic()


def log_env(env: dict):
    imu = env.get('imu') or {}
    _csv_buffer.append([
        time.strftime('%Y-%m-%d %H:%M:%S'),
        env.get('light', ''),
        env.get('light_lux', ''),
        env.get('temp_c', ''),
        env.get('smoke', ''),
        env.get('volume', ''),
        env.get('crying', ''),
        env.get('cry_score', ''),
        env.get('dist_cm', ''),
        env.get('track', ''),
        env.get('alarm', ''),
        imu.get('yaw', ''),
        imu.get('roll', ''),
        imu.get('pitch', ''),
        env.get('fps', ''),
    ])
    if (
        len(_csv_buffer) >= _CSV_FLUSH_COUNT
        or time.monotonic() - _csv_last_flush >= _CSV_FLUSH_SECS
    ):
        flush_csv()
