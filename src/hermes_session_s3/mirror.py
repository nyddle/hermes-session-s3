"""Background best-effort mirroring of ``~/.hermes/sessions`` to S3."""

from __future__ import annotations

import getpass
import json
import logging
import mimetypes
import os
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
STATE_VERSION = 1


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
    """Best-effort poller that mirrors session files into S3."""

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
        now = time.time()
        uploaded = 0

        for path in self._iter_files():
            rel_path = path.relative_to(self.sessions_dir).as_posix()
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
                body = path.read_bytes()
            except FileNotFoundError:
                continue
            except Exception:
                logger.warning("Failed to read session file: %s", path, exc_info=True)
                continue

            key = self._build_s3_key(rel_path)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

            try:
                client.put_object(
                    Bucket=self.config.bucket,
                    Key=key,
                    Body=body,
                    ContentType=content_type,
                    Metadata={"source": "hermes-sessions", "relative-path": rel_path},
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
            if any(part.startswith(".") for part in path.parts):
                continue
            files.append(path)
        files.sort()
        return files

    def _build_s3_key(self, rel_path: str) -> str:
        month_and_user = f"{datetime.now():%Y-%m}-{getpass.getuser() or 'unknown'}"
        return "/".join([self.config.prefix, month_and_user, rel_path])

    def _load_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"version": STATE_VERSION, "files": {}}

        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Failed to read state file %s", self.state_file, exc_info=True)
            return {"version": STATE_VERSION, "files": {}}

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

