"""Designation schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CreateDesignationDataRequest(BaseModel):
    """Request to create designation data."""

    position_name: str
    organizational_unit: str | None = None
    start_date: date | None = None
    legal_basis: str | None = None
    appointing_authority: str | None = None
    salary_category: str | None = None
    work_schedule: str | None = None
    observations: str | None = None
    model_config = ConfigDict(extra="forbid")


class DesignationDataResponse(BaseModel):
    """Designation data response."""

    id: UUID
    case_file_id: UUID
    position_name: str
    organizational_unit: str | None = None
    start_date: date | None = None
    legal_basis: str | None = None
    appointing_authority: str | None = None
    salary_category: str | None = None
    work_schedule: str | None = None
    observations: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
