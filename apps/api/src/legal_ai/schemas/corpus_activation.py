"""DTOs for the fail-closed staged-index activation command."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CorpusActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_database: str = Field(min_length=1, max_length=128)
    generation: int = Field(default=1, gt=0)
    batch_size: int = Field(default=100, gt=0, le=1000)

    @field_validator("expected_database")
    @classmethod
    def validate_database_name(cls, value: str) -> str:
        cleaned = value.strip()
        safe = all(
            character.isalnum() or character == "_" for character in cleaned
        )
        if not cleaned or not safe:
            raise ValueError("CORPUS_ACTIVATION_DATABASE_INVALID")
        return cleaned


class CorpusActivationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_mode: Literal["DRY_RUN", "EXECUTE"]
    status: Literal["ready", "completed", "failed"]
    database_verified: bool
    generation: int
    documents_total: int = Field(ge=0)
    documents_pending: int = Field(ge=0)
    documents_activated: int = Field(ge=0)
    documents_already_active: int = Field(ge=0)
    chunks_total: int = Field(ge=0)
    chunks_staged: int = Field(ge=0)
    chunks_active: int = Field(ge=0)
    embeddings_present: int = Field(ge=0)
    review_version_checksum: int = Field(ge=0)
    violations: tuple[str, ...] = ()
