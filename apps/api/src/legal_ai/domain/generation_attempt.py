"""GenerationAttempt domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from legal_ai.domain.enums import GenerationStatus


@dataclass
class GenerationAttempt:
    """Intento de generación de borrador."""

    id: UUID
    case_file_id: UUID
    template_id: UUID
    model: str
    prompt_hash: str
    prompt_content: str
    status: GenerationStatus
    started_at: datetime
    created_at: datetime
    idempotency_key: str | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
