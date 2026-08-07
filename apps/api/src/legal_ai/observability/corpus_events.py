"""Allowlisted events emitted by corpus workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_ALLOWED = frozenset(
    {
        "request_id",
        "ingestion_run_id",
        "batch_id",
        "query_id",
        "document_id",
        "status",
        "stage",
        "model",
        "dimensions",
        "duration_ms",
        "result_count",
        "error_code",
        "priority",
    }
)
_FORBIDDEN = frozenset(
    {
        "raw_content",
        "normalized_content",
        "query",
        "embedding",
        "vector",
        "authorization",
        "token",
        "storage_path",
        "stack_trace",
    }
)


def sanitize_event_fields(fields: dict[str, Any]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in fields.items():
        lowered = key.casefold()
        if key not in _ALLOWED or lowered in _FORBIDDEN:
            continue
        if isinstance(value, bool | int | float):
            result[key] = value
        elif isinstance(value, str) and value and len(value) <= 256:
            result[key] = " ".join(value.split())
    return result


@dataclass(frozen=True, slots=True)
class CorpusEvent:
    event: str
    fields: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def safe_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "event": self.event,
            "created_at": self.created_at.isoformat(),
        }
        payload.update(sanitize_event_fields(self.fields))
        return payload
