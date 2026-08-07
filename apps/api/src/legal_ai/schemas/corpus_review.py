"""Strict request and response DTOs for corpus document review."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CorpusReviewRequest(BaseModel):
    """Allow exactly one terminal review decision and no arbitrary fields."""

    model_config = ConfigDict(extra="forbid")

    document_id: uuid.UUID
    approve: bool = False
    reject: bool = False
    reason: str | None = Field(default=None, max_length=1000)
    reviewed_by: str = Field(min_length=1, max_length=200)
    expected_version: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_decision(self) -> CorpusReviewRequest:
        if self.approve == self.reject:
            raise ValueError("CORPUS_REVIEW_DECISION_REQUIRED")
        if not self.reviewed_by.strip():
            raise ValueError("CORPUS_REVIEW_REVIEWED_BY_REQUIRED")
        if self.reject and (self.reason is None or not self.reason.strip()):
            raise ValueError("CORPUS_REVIEW_REASON_REQUIRED")
        if self.approve and self.reason is not None:
            raise ValueError("CORPUS_REVIEW_REASON_NOT_ALLOWED")
        return self


class CorpusReviewResult(BaseModel):
    """Safe response; document body and ORM fields are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    document_id: uuid.UUID
    status: str
    review_version: int = Field(gt=0)
    reviewed_by: str
    reviewed_at: datetime
    request_id: str | None = None
