"""HTTP schemas for human review and comments."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from legal_ai.domain.enums import CommentSeverity, CommentStatus, ReviewStatus
from legal_ai.schemas.validation import ActorValidated


class ReviewCreateRequest(ActorValidated, BaseModel):
    draft_version: int = Field(gt=0)
    expected_version: int = Field(gt=0)
    opened_by: str
    model_config = ConfigDict(extra="forbid")


class ReviewCommentCreateRequest(ActorValidated, BaseModel):
    author: str
    expected_version: int = Field(gt=0)
    body: str = Field(min_length=1, max_length=10000)
    severity: CommentSeverity
    draft_version: int = Field(gt=0)
    anchor: dict[str, Any] | None = None
    parent_comment_id: UUID | None = None
    model_config = ConfigDict(extra="forbid")


class ReviewCommentUpdateRequest(ActorValidated, BaseModel):
    expected_version: int = Field(gt=0)
    status: CommentStatus
    resolved_by: str | None = None
    model_config = ConfigDict(extra="forbid")


class ReviewSubmitRequest(ActorValidated, BaseModel):
    expected_version: int = Field(gt=0)
    submitted_by: str
    model_config = ConfigDict(extra="forbid")


class ReviewApproveRequest(ActorValidated, BaseModel):
    expected_version: int = Field(gt=0)
    decided_by: str
    human_review_confirmed: bool
    model_config = ConfigDict(extra="forbid")


class ReviewRequestChangesRequest(ActorValidated, BaseModel):
    expected_version: int = Field(gt=0)
    decided_by: str
    reason: str = Field(min_length=1, max_length=2000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("reason must be a string")
        reason = value.strip()
        if not reason:
            raise ValueError("reason must not be empty")
        return reason


class ReviewResponse(BaseModel):
    id: UUID
    draft_id: UUID
    draft_version: int
    review_snapshot_sha256: str
    status: ReviewStatus
    version: int
    opened_by: str
    submitted_by: str | None = None
    decided_by: str | None = None
    opened_at: datetime
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ReviewCommentResponse(BaseModel):
    id: UUID
    review_id: UUID
    parent_comment_id: UUID | None = None
    draft_version: int
    author: str
    severity: CommentSeverity
    status: CommentStatus
    body: str
    anchor: dict[str, Any] | None = None
    version: int
    created_at: datetime
    updated_at: datetime
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class ReviewEventResponse(BaseModel):
    id: UUID
    resource_type: str
    resource_id: str | None = None
    event_type: str
    actor: str | None = None
    request_id: str | None = None
    run_id: UUID | None = None
    draft_version: int | None = None
    summary: dict[str, Any]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
