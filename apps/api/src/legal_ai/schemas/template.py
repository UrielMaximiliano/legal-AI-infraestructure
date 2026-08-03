"""Template schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from legal_ai.domain.enums import TemplateDocumentType


class CreateTemplateRequest(BaseModel):
    """Request to create a template."""

    name: str
    document_type: TemplateDocumentType
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    body_template: str
    variables: list[str] = []
    model_config = ConfigDict(extra="forbid")


class UpdateTemplateRequest(BaseModel):
    """Request to update a template."""

    body_template: str | None = None
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    variables: list[str] | None = None
    model_config = ConfigDict(extra="forbid")


class TemplateResponse(BaseModel):
    """Template response."""

    id: UUID
    name: str
    document_type: TemplateDocumentType
    version: int
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    body_template: str
    variables: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
