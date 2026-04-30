"""Runtime JSON tuning for motion parameters."""

import json
import os
import time
from dataclasses import fields
from typing import Iterable


class JsonTuner:
    """Hot-load dataclass fields from a JSON file."""

    def __init__(self, path: str, config, poll_sec: float = 0.25):
        self.path = os.path.abspath(path)
        self.poll_sec = float(poll_sec)
        self._next_check = 0.0
        self._mtime = None
        self._allowed = {f.name for f in fields(config)}
        self._types = {f.name: f.type for f in fields(config)}
        self.last_error = ""
        self.last_loaded_at = 0.0
        self.last_changed = []
        self._ensure_file(config)

    def maybe_apply(self, config) -> list:
        now = time.monotonic()
        if now < self._next_check:
            return []
        self._next_check = now + self.poll_sec

        try:
            mtime = os.path.getmtime(self.path)
        except OSError as exc:
            self.last_error = str(exc)
            return []

        if self._mtime is not None and mtime == self._mtime:
            return []
        self._mtime = mtime

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            self.last_error = f"load failed: {exc}"
            return []

        if not isinstance(payload, dict):
            self.last_error = "root must be a JSON object"
            return []

        changed = []
        for key, value in payload.items():
            if key.startswith("_") or key not in self._allowed:
                continue
            old = getattr(config, key)
            new = self._coerce(value, old, self._types.get(key))
            if new != old:
                setattr(config, key, new)
                changed.append(key)

        self.last_error = ""
        self.last_loaded_at = time.time()
        self.last_changed = changed
        return changed

    def summary(self, names: Iterable[str], config) -> str:
        parts = []
        for name in names:
            if hasattr(config, name):
                parts.append(f"{name}={getattr(config, name)}")
        return " ".join(parts)

    def _ensure_file(self, config):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.exists(self.path):
            return

        data = {
            "_comment": "Edit values while PC client is running; changes hot-load automatically.",
        }
        for f in fields(config):
            data[f.name] = getattr(config, f.name)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    @staticmethod
    def _coerce(value, old, expected=None):
        if expected is bool or isinstance(old, bool):
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
        if expected is float:
            return float(value)
        if expected is int or (isinstance(old, int) and not isinstance(old, bool)):
            return int(value)
        if isinstance(old, float):
            return float(value)
        return value
