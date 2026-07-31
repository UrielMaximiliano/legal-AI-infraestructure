"""Employee schemas for request/response."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from legal_ai.domain.enums import DocumentType


class CreateEmployeeRequest(BaseModel):
    """Request schema for creating an employee."""

    model_config = ConfigDict(extra="forbid")

    employee_number: str
    first_name: str
    last_name: str
    document_type: DocumentType
    document_number: str
    cuil: str | None = None
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    department: str | None = None


class UpdateEmployeeRequest(BaseModel):
    """Request schema for updating an employee."""

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    department: str | None = None


class EmployeeResponse(BaseModel):
    """Response schema for an employee."""

    id: UUID
    employee_number: str
    first_name: str
    last_name: str
    document_type: DocumentType
    document_number: str
    cuil: str | None = None
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    department: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime
