"""PC-side wire protocol — imports canonical shared definitions, adds PC-only infrastructure.

Shared symbols (from raspbot_shared.protocol):
  MSG_VIDEO, MSG_COMMAND, MSG_ENV
  AUTH_QUERY_KEY, AUTH_FIELD
  PLAY_SONG_NEXT, PLAY_SONG_PREV, PLAY_SONG_RANDOM
  resolve_auth_token, validate_auth_config, is_ws_authorized, auth_token_from_ws, safe_ws_path
  clamp_int, as_bool
  ImuPacket, CommandPacket, EnvPacket

PC-only extensions: WebRTC signaling types, auth helpers for cloud bridge,
BackgroundService runner.
"""

import os as _os
import sys as _sys

# Ensure raspbot_shared is importable (needed when tests add only raspbot1/ to sys.path)
_repo = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _repo not in _sys.path:
    _sys.path.insert(0, _repo)

from raspbot_shared.protocol import (
    MSG_VIDEO, MSG_COMMAND, MSG_ENV,
    AUTH_QUERY_KEY, AUTH_FIELD,
    PLAY_SONG_NEXT, PLAY_SONG_PREV, PLAY_SONG_RANDOM,
    resolve_auth_token, validate_auth_config, is_ws_authorized, auth_token_from_ws, safe_ws_path,
    _is_loopback_host,
    clamp_int, as_bool,
    ImuPacket, CommandPacket, EnvPacket,
)

# ── PC-only WebRTC signaling types ─────────────────────────────────

TYPE_APP_VOICE      = "app_voice"
TYPE_WEBRTC_OFFER   = "webrtc_offer"
TYPE_WEBRTC_ANSWER  = "webrtc_answer"
TYPE_WEBRTC_ICE     = "webrtc_ice"
TYPE_ENV_SUBSCRIBE  = "env_subscribe"
TYPE_ENV_UPDATE     = "env_update"

# ── PC-only auth helpers (cloud bridge) ────────────────────────────

import hmac
import logging
import threading
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def append_auth_token_to_uri(uri: str, auth_token: Optional[str]) -> str:
    token = resolve_auth_token(auth_token)
    if not token:
        return uri
    parts = urlsplit(uri)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params[AUTH_QUERY_KEY] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


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


# ── PC-only background service runner ─────────────────────────────

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
            import asyncio
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

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
