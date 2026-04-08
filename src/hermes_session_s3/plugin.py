"""Hermes plugin hooks for request/response dumps and S3 session mirroring."""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .mirror import SessionS3MirrorService, get_hermes_home

logger = logging.getLogger(__name__)


class SessionAuditPlugin:
    """Write debug dump files and trigger S3 sync from Hermes plugin hooks."""

    def __init__(self) -> None:
        hermes_home = get_hermes_home()
        self.sessions_dir = hermes_home / "sessions"
        self._lock = threading.Lock()
        self._pending_dump_tokens: dict[tuple[str, str, str], str] = {}
        self._mirror_service: SessionS3MirrorService | None = None
        self._sync_thread: threading.Thread | None = None
        self._sync_requested = False
        self._sync_force_requested = False

    def pre_api_request(self, **kwargs) -> None:
        request_debug = kwargs.get("request_debug")
        if not isinstance(request_debug, dict):
            return

        session_id = self._safe_session_id(kwargs.get("session_id"))
        dump_token = self._dump_token()
        call_key = self._call_key(kwargs)

        with self._lock:
            self._pending_dump_tokens[call_key] = dump_token

        payload = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "task_id": kwargs.get("task_id"),
            "api_call_count": kwargs.get("api_call_count"),
            "platform": kwargs.get("platform"),
            "model": kwargs.get("model"),
            "provider": kwargs.get("provider"),
            "reason": "plugin_pre_api_request",
            "request": request_debug,
        }
        self._write_dump(f"request_dump_{session_id}_{dump_token}.json", payload)

    def post_api_request(self, **kwargs) -> None:
        response_debug = kwargs.get("response_debug")
        if not isinstance(response_debug, dict):
            return

        session_id = self._safe_session_id(kwargs.get("session_id"))
        call_key = self._call_key(kwargs)
        with self._lock:
            dump_token = self._pending_dump_tokens.pop(call_key, self._dump_token())

        payload = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "task_id": kwargs.get("task_id"),
            "api_call_count": kwargs.get("api_call_count"),
            "platform": kwargs.get("platform"),
            "model": kwargs.get("model"),
            "provider": kwargs.get("provider"),
            "response_model": kwargs.get("response_model"),
            "reason": "plugin_post_api_request",
            "response": response_debug,
        }
        self._write_dump(f"response_dump_{session_id}_{dump_token}.json", payload)
        # The response dump has just been fully written, so we can bypass the
        # settle delay here. Running in the background keeps the UI responsive.
        self._request_sync(force=True)

    def on_session_end(self, **kwargs) -> None:
        self._sync_sessions(force=True)

    def _request_sync(self, *, force: bool) -> None:
        with self._lock:
            self._sync_requested = True
            self._sync_force_requested = self._sync_force_requested or force
            if self._sync_thread and self._sync_thread.is_alive():
                return
            self._sync_thread = threading.Thread(
                target=self._sync_worker,
                name="hermes-session-s3-sync",
                daemon=True,
            )
            self._sync_thread.start()

    def _sync_worker(self) -> None:
        while True:
            with self._lock:
                if not self._sync_requested:
                    self._sync_thread = None
                    return
                force = self._sync_force_requested
                self._sync_requested = False
                self._sync_force_requested = False

            self._sync_sessions(force=force)
            time.sleep(0.05)

    def _sync_sessions(self, *, force: bool) -> None:
        service = self._get_mirror_service()
        if service is None or not service.enabled:
            return
        try:
            service.scan_once(force=force)
        except Exception:
            logger.warning("Hermes session S3 plugin sync failed", exc_info=True)

    def _get_mirror_service(self) -> SessionS3MirrorService | None:
        if self._mirror_service is None:
            self._mirror_service = SessionS3MirrorService()
        return self._mirror_service

    def _write_dump(self, filename: str, payload: dict[str, Any]) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self.sessions_dir / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _call_key(kwargs: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(kwargs.get("session_id") or ""),
            str(kwargs.get("api_call_count") or ""),
            str(kwargs.get("task_id") or ""),
        )

    @staticmethod
    def _dump_token() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]
        return f"{timestamp}Z_{secrets.token_hex(4)}"

    @staticmethod
    def _safe_session_id(value: Any) -> str:
        text = str(value or "").strip()
        return text or "unknown_session"


_plugin = SessionAuditPlugin()


def register(ctx) -> None:
    ctx.register_hook("pre_api_request", _plugin.pre_api_request)
    ctx.register_hook("post_api_request", _plugin.post_api_request)
    ctx.register_hook("on_session_end", _plugin.on_session_end)
