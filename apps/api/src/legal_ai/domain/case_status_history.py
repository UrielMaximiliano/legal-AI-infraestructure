"""Case status history domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from legal_ai.domain.enums import CaseStatus


@dataclass
class CaseStatusHistory:
    """Case status history domain entity."""

    id: UUID
    case_file_id: UUID
    to_status: CaseStatus
    changed_by: str
    from_status: CaseStatus | None = None
    reason: str | None = None
    request_id: str | None = None
    changed_at: datetime = field(default_factory=datetime.now)
