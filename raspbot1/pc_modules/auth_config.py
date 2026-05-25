"""Local auth token and runtime configuration helpers."""

import json
import os
import secrets
from pathlib import Path

from .logger_setup import setup_logger

logger = setup_logger("raspbot.auth-config")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_CONFIG_PATH = PROJECT_ROOT / "raspbot.local.json"
ANDROID_LOCAL_PROPERTIES_PATH = PROJECT_ROOT.parent / "RaspbotApp" / "local.properties"
AUTH_TOKEN_ENV = "RASPBOT_AUTH_TOKEN"
ALLOW_INSECURE_ENV = "RASPBOT_ALLOW_INSECURE"


def env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _escape_properties_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")


def read_local_config(path: Path = LOCAL_CONFIG_PATH) -> dict:
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("cannot read local config %s: %s", path, exc)
        return {}


def write_local_config(config: dict, path: Path = LOCAL_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def set_local_env_value(key: str, value: str, path: Path = LOCAL_CONFIG_PATH) -> bool:
    cfg = read_local_config(path)
    env = cfg.get("env")
    if not isinstance(env, dict):
        env = {}
        cfg["env"] = env
    if str(env.get(key, "") or "").strip() == value:
        return False
    env[key] = value
    write_local_config(cfg, path)
    return True


def sync_android_auth_token(token: str, path: Path = ANDROID_LOCAL_PROPERTIES_PATH) -> bool:
    token = str(token or "").strip()
    if not token:
        return False
    line_value = f"{AUTH_TOKEN_ENV}={_escape_properties_value(token)}"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    lines = text.splitlines(keepends=True)
    updated = False
    found = False
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped and stripped[0] not in "#!":
            key_part = stripped.split("=", 1)[0].split(":", 1)[0].strip()
            if key_part == AUTH_TOKEN_ENV:
                found = True
                newline = "\r\n" if line.endswith("\r\n") else "\n"
                replacement = line_value + newline
                out.append(replacement)
                updated = updated or replacement != line
                continue
        out.append(line)
    if not found:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += "\n"
            updated = True
        out.append(line_value + "\n")
        updated = True
    if updated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(out), encoding="utf-8")
    return updated


def ensure_auth_token(
    requested_token: str = "",
    *,
    config_path: Path = LOCAL_CONFIG_PATH,
    android_properties_path: Path = ANDROID_LOCAL_PROPERTIES_PATH,
) -> str:
    auth_token = str(requested_token or os.getenv(AUTH_TOKEN_ENV, "")).strip()
    if not auth_token and not env_truthy(ALLOW_INSECURE_ENV):
        cfg = read_local_config(config_path)
        env = cfg.get("env", {})
        if isinstance(env, dict):
            auth_token = str(env.get(AUTH_TOKEN_ENV, "") or "").strip()
    if not auth_token:
        if env_truthy(ALLOW_INSECURE_ENV):
            logger.warning(
                "%s is not set; continuing because %s=1 is enabled for this environment",
                AUTH_TOKEN_ENV,
                ALLOW_INSECURE_ENV,
            )
            return ""
        auth_token = secrets.token_urlsafe(32)
        logger.info("generated local %s for authenticated car/app websocket startup", AUTH_TOKEN_ENV)
    changed_config = set_local_env_value(AUTH_TOKEN_ENV, auth_token, path=config_path)
    changed_app = sync_android_auth_token(auth_token, path=android_properties_path)
    os.environ[AUTH_TOKEN_ENV] = auth_token
    if changed_config:
        logger.info("saved %s to %s", AUTH_TOKEN_ENV, config_path.name)
    if changed_app:
        logger.info("synced %s to Android local.properties", AUTH_TOKEN_ENV)
    return auth_token
