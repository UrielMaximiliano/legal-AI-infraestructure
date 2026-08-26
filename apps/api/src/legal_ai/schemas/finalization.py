"""HTTP schemas for write-once draft finalization."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from legal_ai.schemas.validation import ActorValidated


class FinalizeDraftRequest(ActorValidated, BaseModel):
    expected_version: int = Field(gt=0)
    finalized_by: str
    official_number: int = Field(gt=0, le=999999)
    issued_on: date
    finalization_notes: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("finalization_notes", mode="before")
    @classmethod
    def trim_notes(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("finalization_notes must be a string")
        notes = value.strip()
        return notes or None


class FinalizationResponse(BaseModel):
    draft_id: UUID
    draft_version: int
    finalized_by: str
    finalized_at: datetime
    finalization_notes: str | None = None
    final_snapshot: dict[str, Any]
    final_snapshot_sha256: str
    official_number: int
    issued_on: date
    model_config = ConfigDict(from_attributes=True)
