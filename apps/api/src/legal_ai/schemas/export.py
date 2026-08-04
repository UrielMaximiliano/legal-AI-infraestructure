"""Schemas reserved for 004 export metadata and pipeline contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from legal_ai.domain.enums import ExportAttemptStatus, ExportFormat, ExportStatus
from legal_ai.schemas.validation import ActorValidated


class CreateExportRequest(ActorValidated, BaseModel):
    draft_version: int = Field(gt=0)
    format: str
    exported_by: str
    model_config = ConfigDict(extra="forbid")


class RetryExportRequest(ActorValidated, BaseModel):
    exported_by: str
    model_config = ConfigDict(extra="forbid")


class RegenerateExportRequest(ActorValidated, BaseModel):
    expected_version: int = Field(
        gt=0,
        validation_alias=AliasChoices("expected_version", "expected_export_version"),
    )
    exported_by: str
    model_config = ConfigDict(extra="forbid")


class ExportResponse(BaseModel):
    id: UUID
    draft_id: UUID
    draft_version: int
    review_id: UUID
    export_version: int
    parent_export_id: UUID | None = None
    format: ExportFormat
    status: ExportStatus
    file_name: str
    source_snapshot_sha256: str
    content_sha256: str | None = None
    renderer_name: str | None = None
    renderer_version: str | None = None
    exported_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    request_id: str | None = None
    model_config = ConfigDict(from_attributes=True)


class ExportAttemptResponse(BaseModel):
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
    error_code: str | None = None
    error_message: str | None = None
    model_config = ConfigDict(from_attributes=True)


class ExportListItem(ExportResponse):
    """Metadata-only list item; storage path is intentionally absent."""


class SafeMetadata(BaseModel):
    """Small typed container for sanitized response details."""

    values: dict[str, Any] = Field(default_factory=dict)
