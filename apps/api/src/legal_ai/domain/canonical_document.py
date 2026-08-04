"""Canonical document value object shared by later renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CanonicalDocument:
    """Serializable document shape without renderer or persistence concerns."""

    schema_version: int
    draft_id: str
    source_draft_version: int
    finalized_version: int
    source_content_sha256: str
    document: dict[str, Any] = field(default_factory=dict)
    source_text: str = ""

    def as_snapshot(self) -> dict[str, Any]:
        """Return a plain serializable snapshot for hashing/persistence."""
        return {
            "schema_version": self.schema_version,
            "draft_id": self.draft_id,
            "source_draft_version": self.source_draft_version,
            "finalized_version": self.finalized_version,
            "source_content_sha256": self.source_content_sha256,
            "document": self.document,
            "source_text": self.source_text,
        }
