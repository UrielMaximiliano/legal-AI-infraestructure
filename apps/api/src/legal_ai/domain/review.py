"""Versioned human-review domain entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from legal_ai.domain.enums import ReviewStatus


@dataclass
class DocumentReview:
    """Review bound to one immutable draft version and snapshot."""

    id: UUID
    draft_id: UUID
    draft_version: int
    review_snapshot: dict[str, object]
    review_snapshot_sha256: str
    status: ReviewStatus
    opened_by: str
    version: int
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    submitted_by: str | None = None
    decided_by: str | None = None
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    closed_at: datetime | None = None

    def is_closed(self) -> bool:
        """Return whether no further review mutation is allowed."""
        return self.status == ReviewStatus.CLOSED or self.closed_at is not None

    def has_approved_decision(self) -> bool:
        """Return whether this review represents an approved decision."""
        return self.status == ReviewStatus.CLOSED and self.decided_at is not None


@dataclass
class ReviewOperationRequest:
    """Persisted idempotency claim for one review mutation."""

    id: UUID
    operation: str
    resource_id: UUID
    idempotency_key: str
    request_hash: str
    status: str
    expires_at: datetime
    request_id: str
    created_at: datetime
    response_status: int | None = None
    response_payload: dict[str, object] | None = None
    error_code: str | None = None
    completed_at: datetime | None = None


@dataclass
class ReviewState:
    """Small immutable-friendly state helper for service transitions."""

    status: ReviewStatus
    version: int
    open_blocking_comments: int = field(default=0)
