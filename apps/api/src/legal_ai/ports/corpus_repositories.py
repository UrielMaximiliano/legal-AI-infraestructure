"""Repository ports for corpus and ingestion persistence."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Protocol

from legal_ai.domain.corpus import (
    CorpusActivationDocument,
    CorpusActivationSnapshot,
    CorpusChunk,
    CorpusDeduplicationRecord,
    CorpusDocument,
    CorpusDocumentUpsertResult,
    ReviewStatus,
)
from legal_ai.domain.ingestion import EmbeddingBatch, IngestionFailure, IngestionRun
from legal_ai.domain.semantic_search import HumanRetrievalEvaluation, SemanticSearchRun


class CorpusDeduplicationLookupPort(Protocol):
    """Read-only lookup used by dry-run; it has no write operations."""

    async def lookup(
        self,
        *,
        identities: Sequence[tuple[str, str]],
        normalized_content_hashes: Sequence[str],
    ) -> Sequence[CorpusDeduplicationRecord]: ...


class CorpusActivationRepository(Protocol):
    async def inspect(self, *, generation: int) -> CorpusActivationSnapshot: ...

    async def lock_document(
        self, document_id: uuid.UUID, *, generation: int
    ) -> CorpusActivationDocument: ...

    async def lock_documents(
        self, document_ids: Sequence[uuid.UUID], *, generation: int
    ) -> Sequence[CorpusActivationDocument]: ...


class CorpusDocumentRepository(Protocol):
    async def get(self, document_id: uuid.UUID) -> CorpusDocument | None: ...
    async def compare_and_swap_review(
        self,
        document_id: uuid.UUID,
        *,
        expected_version: int,
        expected_status: ReviewStatus,
        new_status: ReviewStatus,
        reviewed_by: str,
        reason: str | None = None,
    ) -> CorpusDocument: ...

    async def create(self, document: CorpusDocument) -> CorpusDocument: ...

    async def upsert(self, document: CorpusDocument) -> CorpusDocumentUpsertResult: ...

    async def update(self, document: CorpusDocument) -> CorpusDocument: ...

    async def update_processing_state(
        self,
        document_id: uuid.UUID,
        *,
        ingestion_status: str,
        embedding_status: str,
    ) -> CorpusDocument: ...

    async def swap_generation(
        self, document_id: uuid.UUID, generation: int
    ) -> None: ...

    async def swap_generations(
        self, document_ids: Sequence[uuid.UUID], generation: int
    ) -> None: ...

    async def update_processing_states(
        self,
        document_ids: Sequence[uuid.UUID],
        *,
        ingestion_status: str,
        embedding_status: str,
    ) -> None: ...

    async def list(
        self,
        *,
        document_type: str,
        document_subtype: str,
        jurisdiction: str,
        review_status: ReviewStatus | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[CorpusDocument]: ...

    async def count_eligible_reviewed_documents(
        self,
        *,
        evaluation_split: str = "INDEX_90",
        document_type: str | None = None,
        document_subtype: str | None = None,
        jurisdiction: str | None = None,
    ) -> int: ...


class CorpusChunkRepository(Protocol):
    async def create(self, chunk: CorpusChunk) -> CorpusChunk: ...

    async def upsert(self, chunk: CorpusChunk) -> CorpusChunk: ...

    async def update(self, chunk: CorpusChunk) -> CorpusChunk: ...

    async def get(self, chunk_id: uuid.UUID) -> CorpusChunk | None: ...

    async def list_active(
        self, document_id: uuid.UUID, generation: int
    ) -> Sequence[CorpusChunk]: ...

    async def list_generation(
        self, document_id: uuid.UUID, generation: int
    ) -> Sequence[CorpusChunk]: ...

    async def activate_generation(
        self, document_id: uuid.UUID, generation: int
    ) -> None: ...

    async def activate_generations(
        self, document_ids: Sequence[uuid.UUID], generation: int
    ) -> None: ...


class IngestionRepository(Protocol):
    async def create_run(self, run: IngestionRun) -> IngestionRun: ...
    async def save_batch(self, batch: EmbeddingBatch) -> EmbeddingBatch: ...


class IngestionRunRepository(Protocol):
    async def create(self, run: IngestionRun) -> IngestionRun: ...

    async def get(self, run_id: str) -> IngestionRun | None: ...

    async def update(self, run: IngestionRun) -> IngestionRun: ...


class IngestionFailureRepository(Protocol):
    async def create(self, failure: IngestionFailure) -> IngestionFailure: ...

    async def get(self, failure_id: uuid.UUID) -> IngestionFailure | None: ...


class EmbeddingBatchRepository(Protocol):
    async def create(self, batch: EmbeddingBatch) -> EmbeddingBatch: ...

    async def get(self, batch_id: uuid.UUID) -> EmbeddingBatch | None: ...

    async def update(self, batch: EmbeddingBatch) -> EmbeddingBatch: ...

    async def list_for_run(
        self, ingestion_run_id: uuid.UUID, generation: int
    ) -> Sequence[EmbeddingBatch]: ...

    async def list_all_for_run(
        self, ingestion_run_id: uuid.UUID
    ) -> Sequence[EmbeddingBatch]: ...


class SemanticSearchRunRepository(Protocol):
    async def create(self, run: SemanticSearchRun) -> SemanticSearchRun: ...


class HumanRetrievalEvaluationRepository(Protocol):
    async def create(
        self, evaluation: HumanRetrievalEvaluation
    ) -> HumanRetrievalEvaluation: ...
