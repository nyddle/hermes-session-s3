"""Background best-effort mirroring of ``~/.hermes/sessions`` to S3."""

from __future__ import annotations

import getpass
import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT_URL = "https://s3.cloud.ru"
DEFAULT_REGION = "ru-central-1"
DEFAULT_PREFIX = "hermes-sessions"
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_SETTLE_SECONDS = 2.0
STATE_VERSION = 3

REQUEST_DUMP_RE = re.compile(
    r"^request_dump_(?P<session_id>.+)_(?P<token>(?:\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z_[0-9a-f]{8}|\d{8}_\d{6}_\d{6}))\.json$"
)
RESPONSE_DUMP_RE = re.compile(
    r"^response_dump_(?P<session_id>.+)_(?P<token>(?:\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z_[0-9a-f]{8}|\d{8}_\d{6}_\d{6}))\.json$"
)
NEW_TOKEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z_[0-9a-f]{8}$")
OLD_TOKEN_RE = re.compile(r"^\d{8}_\d{6}_\d{6}$")
REDACT_KEY_RE = re.compile(r"authorization|api[-_]?key|secret|token|password|cookie", re.IGNORECASE)


def get_hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", "~/.hermes")).expanduser()


def env_var_enabled(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def should_redact_key(key: str) -> bool:
    return bool(REDACT_KEY_RE.search(key))


def sanitize(value: Any) -> Any:
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if should_redact_key(str(key)) else sanitize(item))
            for key, item in value.items()
        }
    return value


def sanitize_headers(headers: Any) -> dict[str, Any]:
    if not isinstance(headers, dict):
        return {}
    return {
        str(key): ("[REDACTED]" if should_redact_key(str(key)) else value)
        for key, value in headers.items()
    }


@dataclass(frozen=True)
class SessionS3MirrorConfig:
    bucket: str
    access_key_id: str
    secret_access_key: str
    endpoint_url: str
    region: str
    prefix: str

    @classmethod
    def from_env(cls) -> "SessionS3MirrorConfig | None":
        if env_var_enabled("HERMES_DISABLE_SESSION_S3_MIRROR"):
            return None

        bucket = os.getenv("FREE_CODE_LOGS_S3_BUCKET", "").strip()
        access_key_id = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
        secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
        if not bucket or not access_key_id or not secret_access_key:
            return None

        endpoint_url = os.getenv("AWS_ENDPOINT_URL", "").strip() or DEFAULT_ENDPOINT_URL
        region = os.getenv("AWS_DEFAULT_REGION", "").strip() or DEFAULT_REGION
        prefix = (
            os.getenv("HERMES_SESSIONS_S3_PREFIX", "").strip()
            or os.getenv("FREE_CODE_LOGS_S3_PREFIX", "").strip()
            or DEFAULT_PREFIX
        ).strip("/")

        return cls(
            bucket=bucket,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            endpoint_url=endpoint_url,
            region=region,
            prefix=prefix,
        )


class SessionS3MirrorService:
    """Best-effort poller that uploads request/response dumps in free_code layout."""

    def __init__(
        self,
        *,
        config: SessionS3MirrorConfig | None = None,
        sessions_dir: Path | None = None,
        state_file: Path | None = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        settle_seconds: float = DEFAULT_SETTLE_SECONDS,
    ) -> None:
        hermes_home = get_hermes_home()
        self.config = config if config is not None else SessionS3MirrorConfig.from_env()
        self.sessions_dir = sessions_dir or (hermes_home / "sessions")
        self.state_file = state_file or (hermes_home / "cache" / "session_s3_mirror_state.json")
        self.poll_interval_seconds = max(0.25, float(poll_interval_seconds))
        self.settle_seconds = max(0.0, float(settle_seconds))
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._client: Any = None
        self._missing_sdk_logged = False

    @property
    def enabled(self) -> bool:
        return self.config is not None

    def start(self) -> bool:
        if not self.enabled:
            return False

        with self._lock:
            if self._thread and self._thread.is_alive():
                return True

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="hermes-session-s3-mirror",
                daemon=True,
            )
            self._thread.start()
        return True

    def stop(self, *, flush: bool = True) -> None:
        self._stop_event.set()

        thread = None
        with self._lock:
            thread = self._thread
            self._thread = None

        if thread and thread.is_alive():
            thread.join(timeout=max(1.0, self.poll_interval_seconds * 2))

        if flush and self.enabled:
            self.scan_once(force=True)

    def scan_once(self, *, force: bool = False) -> int:
        if not self.enabled or not self.sessions_dir.exists():
            return 0

        client = self._make_client()
        if client is None:
            return 0

        state = self._load_state()
        file_state = state.setdefault("files", {})
        readme_state = state.setdefault("readmes", {})
        now = time.time()
        uploaded = 0
        pending_readmes: dict[str, str] = {}

        for path in self._iter_files():
            rel_path = path.relative_to(self.sessions_dir).as_posix()
            parsed = self._parse_dump_name(path.name)
            if parsed is None:
                continue

            kind, session_id, token = parsed
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue

            current_sig = {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
            if file_state.get(rel_path) == current_sig:
                continue

            if not force and self.settle_seconds > 0:
                age_seconds = max(0.0, now - stat.st_mtime)
                if age_seconds < self.settle_seconds:
                    continue

            try:
                raw_payload = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            except Exception:
                logger.warning("Failed to parse dump file: %s", path, exc_info=True)
                continue

            upload_payload = self._build_upload_payload(
                kind=kind,
                session_id=session_id,
                payload=raw_payload,
            )
            if upload_payload is None:
                continue

            key = self._build_s3_key(
                session_id=session_id,
                filename=f"{self._canonical_stem(token)}_{kind}.json",
            )
            body = json.dumps(upload_payload, ensure_ascii=False, indent=2).encode("utf-8")

            try:
                client.put_object(
                    Bucket=self.config.bucket,
                    Key=key,
                    Body=body,
                    ContentType="application/json",
                    Metadata={
                        "source": "hermes-session-s3",
                        "relative-path": rel_path,
                        "session-id": session_id,
                    },
                )
            except Exception:
                logger.warning(
                    "Failed to mirror %s -> s3://%s/%s",
                    path,
                    self.config.bucket,
                    key,
                    exc_info=True,
                )
                continue

            file_state[rel_path] = current_sig
            uploaded += 1
            pending_readmes[session_id] = self._build_session_readme(
                session_id=session_id,
                payload=raw_payload,
            )

        for session_id, readme in pending_readmes.items():
            readme_hash = hashlib.sha256(readme.encode("utf-8")).hexdigest()
            if readme_state.get(session_id) == readme_hash:
                continue

            key = self._build_s3_key(session_id=session_id, filename="README.md")
            try:
                client.put_object(
                    Bucket=self.config.bucket,
                    Key=key,
                    Body=readme.encode("utf-8"),
                    ContentType="text/markdown",
                    Metadata={"source": "hermes-session-s3", "session-id": session_id},
                )
            except Exception:
                logger.warning(
                    "Failed to mirror README for session %s -> s3://%s/%s",
                    session_id,
                    self.config.bucket,
                    key,
                    exc_info=True,
                )
                continue

            readme_state[session_id] = readme_hash
            uploaded += 1

        if uploaded > 0:
            state["version"] = STATE_VERSION
            state["updated_at"] = datetime.now().isoformat()
            self._save_state(state)

        return uploaded

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.scan_once()
            except Exception:
                logger.debug("Session S3 mirror scan failed", exc_info=True)
            self._stop_event.wait(self.poll_interval_seconds)

    def _iter_files(self) -> list[Path]:
        if not self.sessions_dir.exists():
            return []

        files: list[Path] = []
        for path in self.sessions_dir.rglob("*"):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(self.sessions_dir).parts
            if any(part.startswith(".") for part in rel_parts):
                continue
            if self._parse_dump_name(path.name) is None:
                continue
            files.append(path)
        files.sort()
        return files

    def _build_s3_key(self, *, session_id: str, filename: str) -> str:
        month_and_user = f"{datetime.now():%Y-%m}-{getpass.getuser() or 'unknown'}"
        return "/".join([self.config.prefix, month_and_user, session_id, filename])

    def _load_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"version": STATE_VERSION, "files": {}, "readmes": {}}

        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Failed to read state file %s", self.state_file, exc_info=True)
            return {"version": STATE_VERSION, "files": {}, "readmes": {}}

        if state.get("version") != STATE_VERSION:
            return {"version": STATE_VERSION, "files": {}, "readmes": {}}

        state.setdefault("files", {})
        state.setdefault("readmes", {})
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            atomic_json_write(self.state_file, state)
        except Exception:
            logger.debug("Failed to persist state file %s", self.state_file, exc_info=True)

    def _make_client(self):
        if self._client is not None:
            return self._client

        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except Exception:
            if not self._missing_sdk_logged:
                logger.warning("boto3 is unavailable; Hermes session S3 mirror is disabled.")
                self._missing_sdk_logged = True
            return None

        self._client = boto3.client(
            "s3",
            aws_access_key_id=self.config.access_key_id,
            aws_secret_access_key=self.config.secret_access_key,
            endpoint_url=self.config.endpoint_url,
            region_name=self.config.region,
            config=BotoConfig(s3={"addressing_style": "path"}),
        )
        return self._client

    @staticmethod
    def _parse_dump_name(name: str) -> tuple[str, str, str] | None:
        request_match = REQUEST_DUMP_RE.match(name)
        if request_match:
            return ("request", request_match.group("session_id"), request_match.group("token"))

        response_match = RESPONSE_DUMP_RE.match(name)
        if response_match:
            return ("response", response_match.group("session_id"), response_match.group("token"))

        return None

    @staticmethod
    def _canonical_stem(token: str) -> str:
        if NEW_TOKEN_RE.fullmatch(token):
            return token

        if not OLD_TOKEN_RE.fullmatch(token):
            return token

        date_part, time_part, micro_part = token.split("_")
        millis = micro_part[:3]
        suffix = micro_part[3:] or micro_part
        return (
            f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
            f"T{time_part[:2]}-{time_part[2:4]}-{time_part[4:6]}-{millis}Z_{suffix}"
        )

    @staticmethod
    def _build_upload_payload(
        *,
        kind: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        timestamp = payload.get("timestamp")

        if kind == "request":
            request = payload.get("request")
            if not isinstance(request, dict):
                return None
            return {
                "timestamp": timestamp,
                "sessionId": session_id,
                "source": payload.get("platform") or payload.get("provider") or "unknown",
                "url": request.get("url"),
                "method": request.get("method") or "POST",
                "headers": sanitize_headers(request.get("headers")),
                "body": sanitize(request.get("body")),
            }

        response = payload.get("response")
        if not isinstance(response, dict):
            return None
        return {
            "timestamp": timestamp,
            "sessionId": session_id,
            "status": response.get("status"),
            "headers": sanitize_headers(response.get("headers")),
            "body": sanitize(response.get("body")),
        }

    @staticmethod
    def _build_session_readme(*, session_id: str, payload: dict[str, Any]) -> str:
        platform = payload.get("platform") or "unknown"
        provider = payload.get("provider") or "unknown"
        model = payload.get("model") or payload.get("response_model") or "unknown"
        lines = [
            "# Hermes Session Logs",
            "",
            f"- Session ID: `{session_id}`",
            f"- Platform: `{platform}`",
            f"- Provider: `{provider}`",
            f"- Model: `{model}`",
            "",
            "This directory mirrors Hermes request/response debug dumps to S3",
            "using the same layout as free_code model logs.",
        ]
        return "\n".join(lines) + "\n"
