"""Export-attempt domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from legal_ai.domain.enums import ExportAttemptStatus, ExportFormat


@dataclass
class ExportAttempt:
    """Auditable processing attempt, including failures and retries."""

    id: UUID
    export_id: UUID
    draft_id: UUID
    format: ExportFormat
    idempotency_key: str
    request_hash: str
    attempt_number: int
    status: ExportAttemptStatus
    request_id: str
    exported_by: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
