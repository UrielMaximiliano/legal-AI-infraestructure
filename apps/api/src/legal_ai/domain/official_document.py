"""Official document number reservation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True)
class OfficialDocumentIdentifier:
    id: UUID
    draft_id: UUID
    document_type: str
    number: int
    year: int
    issued_on: date
    created_at: datetime
