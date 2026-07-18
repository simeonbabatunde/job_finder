from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from app.time_utils import utc_now


SENSITIVE_FIELD_MARKERS = (
    "answer",
    "content",
    "cover_letter",
    "file",
    "password",
    "resume",
    "secret",
    "token",
    "url",
)


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("jobmatchkit.events")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    configured_level = os.getenv("STRUCTURED_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, configured_level, logging.INFO))
    logger.propagate = False
    return logger


event_logger = _build_logger()


def url_host(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    return (parsed.netloc or parsed.path).lower() or None


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_FIELD_MARKERS)


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _is_sensitive_key(str(key)) else _safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def log_event(event: str, level: str = "info", **fields: Any) -> None:
    payload = {
        "event": event,
        "timestamp": utc_now().isoformat(),
        **{key: _safe_value(value) for key, value in fields.items()},
    }
    message = json.dumps(payload, sort_keys=True, default=str)
    log_method = getattr(event_logger, level.lower(), event_logger.info)
    log_method(message)
