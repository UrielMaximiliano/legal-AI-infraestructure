"""Case file schemas for request/response."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from legal_ai.domain.enums import CaseStatus, CaseType


class CreateCaseFileRequest(BaseModel):
    """Request schema for creating a case file."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    title: str
    case_type: CaseType
    description: str | None = None


class UpdateCaseFileRequest(BaseModel):
    """Request schema for updating a case file."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    expected_version: int


class TransitionRequest(BaseModel):
    """Request schema for transitioning case file status."""

    model_config = ConfigDict(extra="forbid")

    status: CaseStatus
    expected_version: int
    changed_by: str
    reason: str | None = None


class CaseFileResponse(BaseModel):
    """Response schema for a case file."""

    id: UUID
    case_number: str
    employee_id: UUID
    title: str
    description: str | None = None
    case_type: CaseType
    status: CaseStatus
    version: int
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


class HistoryItem(BaseModel):
    """Schema for a single history item."""

    id: UUID
    case_file_id: UUID
    from_status: CaseStatus | None = None
    to_status: CaseStatus
    changed_at: datetime
    changed_by: str
    reason: str | None = None
    request_id: str | None = None


class HistoryResponse(BaseModel):
    """Response schema for case file history."""

    items: list[HistoryItem]
