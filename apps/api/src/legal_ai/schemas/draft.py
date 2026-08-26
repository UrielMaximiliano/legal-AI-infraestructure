"""Draft schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from legal_ai.domain.enums import DraftStatus, TransitionAction


class GenerateDraftRequest(BaseModel):
    """Request to generate a draft."""

    template_id: UUID
    case_file_id: UUID
    variables: dict[str, str] = {}
    model_config = ConfigDict(extra="forbid")


class EditDraftContentRequest(BaseModel):
    """Request to edit draft content."""

    content: str
    expected_version: int
    model_config = ConfigDict(extra="forbid")


class TransitionDraftRequest(BaseModel):
    """Request to transition draft state."""

    action: TransitionAction
    expected_version: int
    observations: str | None = None
    model_config = ConfigDict(extra="forbid")


class RegenerateDraftRequest(BaseModel):
    """Request to regenerate a draft."""

    observations: str | None = None
    expected_version: int
    model_config = ConfigDict(extra="forbid")


class DraftResponse(BaseModel):
    """Draft response."""

    id: UUID
    template_id: UUID
    case_file_id: UUID
    title: str
    document_type: str = "otros"
    content: str | None = None
    document: dict[str, object] | None = None
    status: DraftStatus
    version: int
    generation_number: int
    variables_used: dict[str, str]
    parent_draft_id: UUID | None = None
    observations: str | None = None
    request_id: str | None = None
    created_at: datetime
    updated_at: datetime
    finalized_by: str | None = None
    finalized_at: datetime | None = None
    finalization_notes: str | None = None
    official_number: int | None = None
    issued_on: date | None = None
    final_snapshot_sha256: str | None = None
    model_config = ConfigDict(from_attributes=True)


class DraftTransitionResponse(BaseModel):
    """Draft transition response."""

    id: UUID
    draft_id: UUID
    from_status: DraftStatus
    to_status: DraftStatus
    action: TransitionAction
    observations: str | None = None
    performed_by: str | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
