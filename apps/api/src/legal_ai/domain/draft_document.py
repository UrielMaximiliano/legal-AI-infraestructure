"""Versioned structured document value object."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DraftDocumentVersion:
    id: UUID
    draft_id: UUID
    version: int
    document: dict[str, Any]
    content: str
    content_sha256: str
    source: str
    edited_by: str | None
    created_at: datetime

    @property
    def document_hash(self) -> str:
        """Compatibility alias for callers using the generic hash vocabulary."""
        return self.content_sha256

    @property
    def created_by(self) -> str | None:
        return self.edited_by
