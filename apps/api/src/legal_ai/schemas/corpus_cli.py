"""Serializable, non-sensitive CLI reports for corpus ingestion."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CorpusFailureReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_identifier: str
    error_code: str
    stage: str = "INGESTION"
    message: str | None = None
    details: dict[str, int] = Field(default_factory=dict)


class CorpusDryRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    request_id: str
    mode: Literal["dry-run", "execute"]
    execution_mode: Literal["DRY_RUN", "EXECUTE"]
    status: Literal["completed", "partial", "failed"]
    files_discovered: int = Field(ge=0)
    files_valid: int = Field(ge=0)
    files_invalid: int = Field(ge=0)
    documents_new_estimate: int = Field(ge=0)
    documents_duplicate_estimate: int = Field(ge=0)
    chunks_estimated: int = Field(ge=0)
    normalization_version: str
    chunking_version: str
    model: str
    dimensions: int
    failures: list[CorpusFailureReport]
    batch_size: int = Field(default=16, gt=0)
    estimated_batch_count: int = Field(default=0, ge=0)
    max_chunks: int = Field(default=100_000, gt=0)
    deduplication: dict[str, int] = Field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "discovered": self.files_discovered,
            "valid": self.files_valid,
            "failed": self.files_invalid,
            "estimated_chunks": self.chunks_estimated,
            "estimated_embeddings": self.chunks_estimated,
        }
