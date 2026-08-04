"""Review comment domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from legal_ai.domain.enums import CommentSeverity, CommentStatus


@dataclass
class ReviewComment:
    """General or anchored review comment; body and anchor are immutable."""

    id: UUID
    review_id: UUID
    draft_version: int
    author: str
    severity: CommentSeverity
    status: CommentStatus
    body: str
    version: int
    created_at: datetime
    updated_at: datetime
    parent_comment_id: UUID | None = None
    anchor: dict[str, object] | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None

    def is_open_blocking(self) -> bool:
        """Return whether this comment blocks review approval."""
        return (
            self.severity == CommentSeverity.BLOCKING
            and self.status == CommentStatus.OPEN
        )
