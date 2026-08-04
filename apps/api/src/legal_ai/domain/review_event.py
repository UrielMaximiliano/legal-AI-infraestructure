"""Append-only review and audit event domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class ReviewEvent:
    """Sanitized audit event; no document body or internal filesystem path."""

    id: UUID
    resource_type: str
    event_type: str
    created_at: datetime
    review_id: UUID | None = None
    draft_id: UUID | None = None
    export_id: UUID | None = None
    attempt_id: UUID | None = None
    resource_id: str | None = None
    actor: str | None = None
    request_id: str | None = None
    run_id: UUID | None = None
    draft_version: int | None = None
    summary: dict[str, object] | None = None
