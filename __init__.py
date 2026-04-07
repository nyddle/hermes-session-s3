"""Hermes plugin entrypoint for the external session S3 integration."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hermes_session_s3.plugin import register

__all__ = ["register"]

