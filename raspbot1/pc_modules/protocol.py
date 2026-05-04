"""Shared PC-side wire protocol constants and infrastructure.

Keep these values aligned with docs/protocol.md and the car/app protocol modules.
"""

import asyncio
import hmac
import logging
import os
import threading
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MSG_VIDEO = 0x01
MSG_COMMAND = 0x02
MSG_ENV = 0x03

TYPE_APP_VOICE = "app_voice"
TYPE_WEBRTC_OFFER = "webrtc_offer"
TYPE_WEBRTC_ANSWER = "webrtc_answer"
TYPE_WEBRTC_ICE = "webrtc_ice"

# Shared playlist navigation sentinels — keep in sync with car-side audio.py.
PLAY_SONG_NEXT = "__next__"
PLAY_SONG_PREV = "__prev__"
PLAY_SONG_RANDOM = "__random__"

AUTH_QUERY_KEY = "token"
AUTH_FIELD = "auth_token"


def resolve_auth_token(value: Optional[str] = None) -> str:
    return str(value if value is not None else os.getenv("RASPBOT_AUTH_TOKEN", "")).strip()


def _is_loopback_host(host) -> bool:
    value = str(host or "").strip().lower()
    return value in {"localhost", "127.0.0.1", "::1"}


def validate_auth_config(
    host,
    auth_token: Optional[str],
    *,
    component: str = "server",
    allow_insecure: Optional[bool] = None,
) -> None:
    token = resolve_auth_token(auth_token)
    if token:
        return
    if allow_insecure is None:
        allow_insecure = os.getenv("RASPBOT_ALLOW_INSECURE", "").strip().lower() in {"1", "true", "yes", "on"}
    if allow_insecure or _is_loopback_host(host):
        return
    raise RuntimeError(
        f"{component} refuses to bind {host!r} without RASPBOT_AUTH_TOKEN; "
        "set RASPBOT_ALLOW_INSECURE=1 only for isolated lab networks"
    )


def _safe_ws_path(ws) -> str:
    path = getattr(ws, "path", None)
    if path:
        return path
    req = getattr(ws, "request", None)
    if req is not None:
        return getattr(req, "path", "") or ""
    return ""


def append_auth_token_to_uri(uri: str, auth_token: Optional[str]) -> str:
    token = resolve_auth_token(auth_token)
    if not token:
        return uri
    parts = urlsplit(uri)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params[AUTH_QUERY_KEY] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def auth_token_from_ws(ws) -> str:
    query = urlsplit(_safe_ws_path(ws)).query
    params = dict(parse_qsl(query, keep_blank_values=True))
    return str(params.get(AUTH_QUERY_KEY, "") or "").strip()


def is_ws_authorized(ws, expected_token: Optional[str]) -> bool:
    token = resolve_auth_token(expected_token)
    if not token:
        return True
    return hmac.compare_digest(auth_token_from_ws(ws), token)


def payload_has_auth(payload: dict, expected_token: Optional[str]) -> bool:
    token = resolve_auth_token(expected_token)
    if not token:
        return True
    if not isinstance(payload, dict):
        return False
    return hmac.compare_digest(str(payload.get(AUTH_FIELD, "") or ""), token)


def strip_auth_fields(payload: dict) -> dict:
    clean = dict(payload)
    clean.pop(AUTH_FIELD, None)
    return clean


class BackgroundService:
    """Run an async service in a background daemon thread.

    Eliminates the triplicated *Runner classes (AppGatewayRunner,
    AsrServerRunner, WebRtcBridgeRunner) by accepting a factory
    callable that returns the async service instance.
    """

    def __init__(self, build_service: Callable[[], object], name: str = "raspbot.service"):
        self._build_service = build_service
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[Exception] = None
        self._log = logging.getLogger(name)

    def _run(self):
        try:
            service = self._build_service()
            asyncio.run(service.run(stop_event=self._stop_event))
        except Exception as exc:
            self._error = exc
            self._log.error('service thread error: %s', exc)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    @property
    def error(self) -> Optional[Exception]:
        return self._error
