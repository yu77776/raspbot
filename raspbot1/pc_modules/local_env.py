"""Load private local configuration defaults for the Raspbot PC tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


BASE_DIR = Path(__file__).resolve().parents[1]
LOCAL_CONFIG_PATH = BASE_DIR / "raspbot.local.json"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"[CONFIG] warn: cannot read {path.name}: {exc}")
        return {}


def load_local_config(path: Path = LOCAL_CONFIG_PATH) -> Dict[str, Any]:
    cfg = _read_json(path)
    env = cfg.get("env", {})
    if isinstance(env, dict):
        for key, value in env.items():
            if key and key not in os.environ:
                os.environ[str(key)] = str(value)
    return cfg


def load_local_env(path: Path = LOCAL_CONFIG_PATH) -> None:
    load_local_config(path)


def load_baidu_asr_config() -> Dict[str, Any]:
    cfg = load_local_config()
    baidu = cfg.get("baidu_asr", {})
    if isinstance(baidu, dict):
        return baidu
    return {}
