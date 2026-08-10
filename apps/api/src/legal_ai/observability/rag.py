"""Allowlisted RAG telemetry without sensitive payload logging."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)
_ALLOWED_KEYS = frozenset(
    {
        "request_id",
        "run_id",
        "status",
        "error_code",
        "model",
        "embedding_model",
        "embedding_dimensions",
        "retrieved_count",
        "selected_count",
        "context_bytes",
        "context_tokens_estimate",
        "retrieval_duration_ms",
        "generation_duration_ms",
        "validation_duration_ms",
        "total_duration_ms",
        "schema_repair_count",
    }
)


def sanitize_rag_event(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return only scalar operational fields approved for structured logs."""

    result: dict[str, Any] = {}
    for key, value in values.items():
        if key not in _ALLOWED_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    return result


def record_rag_event(event: str, values: Mapping[str, Any]) -> None:
    logger.info("rag_event=%s metrics=%s", event, sanitize_rag_event(values))
