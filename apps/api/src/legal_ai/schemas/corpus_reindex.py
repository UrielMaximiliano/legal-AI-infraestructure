"""Safe selection and report DTOs for corpus reindexing."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


class CorpusReindexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: tuple[uuid.UUID, ...] = ()
    document_type: str = "decreto"
    document_subtype: str = "designacion_transitoria"
    jurisdiction: str = "nacion"
    language: str | None = None
    organization: str | None = None
    model: str = EMBEDDING_MODEL
    dimensions: int = Field(default=EMBEDDING_DIMENSIONS, gt=0)
    normalization_version: str = "005-nfc-v1"
    chunking_version: str = "005-legal-v1"
    batch_size: int = Field(default=16, gt=0, le=256)
    run_id: str | None = Field(default=None, max_length=128)
    resume: bool = False

    @model_validator(mode="after")
    def validate_contract(self) -> CorpusReindexRequest:
        if self.model != EMBEDDING_MODEL or self.dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError("EMBEDDING_CONTRACT_INVALID")
        if not self.document_ids and (
            not self.document_type.strip()
            or not self.document_subtype.strip()
            or not self.jurisdiction.strip()
        ):
            raise ValueError("CORPUS_REINDEX_FILTERS_INVALID")
        if self.resume and not self.run_id:
            raise ValueError("CORPUS_REINDEX_RESUME_REQUIRES_RUN_ID")
        return self


class CorpusReindexReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    mode: Literal["dry-run", "execute"]
    execution_mode: Literal["DRY_RUN", "EXECUTE"]
    status: Literal["completed", "partial", "failed"]
    documents_selected: int = Field(ge=0)
    documents_reindexed: int = Field(ge=0)
    chunks_estimated: int = Field(ge=0)
    batches_estimated: int = Field(ge=0)
    model: str
    dimensions: int
    normalization_version: str
    chunking_version: str
    failures: tuple[str, ...] = ()
