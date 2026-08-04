"""Structured logging and sanitized operational events for increment 004."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from collections.abc import Mapping
from typing import Any

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

# Deliberately excludes actors, storage paths, document bodies, prompts,
# tokens, secrets and arbitrary exception details.
_ALLOWED_FIELDS = frozenset(
    {
        "event",
        "request_id",
        "run_id",
        "draft_id",
        "case_file_id",
        "review_id",
        "export_id",
        "attempt_id",
        "format",
        "export_version",
        "attempt_number",
        "renderer",
        "phase",
        "operation",
        "status",
        "result",
        "duration_ms",
        "validation_duration_ms",
        "total_duration_ms",
        "size_bytes",
        "sha256",
        "error_code",
        "resource_type",
        "action",
        "candidates",
        "deleted",
        "omitted",
        "conflicts",
        "errors",
        "count",
    }
)
_HASH_FIELDS = frozenset({"sha256"})
_ID_FIELDS = frozenset(
    {
        "request_id",
        "run_id",
        "draft_id",
        "case_file_id",
        "review_id",
        "export_id",
        "attempt_id",
    }
)
_SAFE_EVENT_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


class JsonEventFormatter(logging.Formatter):
    """Serialize already-sanitized event records as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "structured_event", None)
        if isinstance(event, Mapping):
            payload = dict(event)
            payload.setdefault("level", record.levelname)
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return super().format(record)


def setup_logging(level: str = "INFO") -> None:
    """Configure the application logger with a JSON-capable formatter."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(JsonEventFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def set_request_id(value: str | None) -> contextvars.Token[str | None]:
    """Set the request correlation id for logs in the current context."""
    return _request_id.set(_safe_scalar(value))


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    """Restore the previous request correlation id."""
    _request_id.reset(token)


def current_request_id() -> str | None:
    """Return the current correlation id without exposing request state."""
    return _request_id.get()


def log_event(
    event: str,
    *,
    level: int = logging.INFO,
    logger: logging.Logger | None = None,
    **fields: Any,
) -> None:
    """Emit one allow-listed, scalar, sanitized operational event."""
    if not event or any(char not in _SAFE_EVENT_CHARS for char in event):
        return
    payload: dict[str, object] = {"event": event}
    request_id = fields.get("request_id") or current_request_id()
    if request_id:
        payload["request_id"] = _safe_scalar(request_id)
    for key, value in fields.items():
        if key not in _ALLOWED_FIELDS or key in {"event", "request_id"}:
            continue
        sanitized = _sanitize_field(key, value)
        if sanitized is not None:
            payload[key] = sanitized
    target = logger or logging.getLogger("legal_ai.004")
    target.log(level, "structured_event", extra={"structured_event": payload})


def _sanitize_field(key: str, value: Any) -> object | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    text = _safe_scalar(value)
    if text is None:
        return None
    if key in _HASH_FIELDS and (
        len(text) != 64 or any(char not in "0123456789abcdefABCDEF" for char in text)
    ):
        return None
    if key in _ID_FIELDS and len(text) > 128:
        return None
    return text


def _safe_scalar(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text or len(text) > 256 or "\n" in text or "\r" in text:
        return None
    # Absolute paths are never valid observability values.
    if text.startswith(("/", "\\")) or (len(text) >= 3 and text[1] == ":"):
        return None
    return text
