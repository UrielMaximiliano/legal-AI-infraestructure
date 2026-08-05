"""Structured corpus logging with central redaction."""

from __future__ import annotations

import logging
from typing import Any, cast

from legal_ai.observability.corpus_events import CorpusEvent
from legal_ai.observability.logging import log_event


def log_corpus_event(
    event: str, *, logger: logging.Logger | None = None, **fields: Any
) -> None:
    """Emit only the corpus event allowlist; payloads never reach logging."""
    safe = CorpusEvent(event, fields).safe_dict()
    safe.pop("event", None)
    safe.pop("created_at", None)
    log_event(event, logger=logger, **cast("dict[str, Any]", safe))


def redact_exception(exc: BaseException) -> str:
    """Return a stable error code, never an exception message or traceback."""
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code else "CORPUS_OPERATION_FAILED"
