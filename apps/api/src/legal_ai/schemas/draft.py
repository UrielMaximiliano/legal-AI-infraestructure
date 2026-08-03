"""Draft schemas."""

from __future__ import annotations

from datetime import datetime
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
    content: str | None = None
    status: DraftStatus
    version: int
    generation_number: int
    variables_used: dict[str, str]
    parent_draft_id: UUID | None = None
    observations: str | None = None
    request_id: str | None = None
    created_at: datetime
    updated_at: datetime
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
