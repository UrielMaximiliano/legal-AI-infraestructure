"""Generation attempt schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from legal_ai.domain.enums import GenerationStatus


class GenerationAttemptResponse(BaseModel):
    """Generation attempt response."""

    id: UUID
    case_file_id: UUID
    template_id: UUID
    idempotency_key: str | None = None
    model: str
    prompt_hash: str
    status: GenerationStatus
    started_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
