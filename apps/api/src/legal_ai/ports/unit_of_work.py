"""Contract for the 005 repositories participating in a short UoW."""

from __future__ import annotations

from typing import Protocol

from .corpus_repositories import (
    CorpusActivationRepository,
    CorpusChunkRepository,
    CorpusDocumentRepository,
    EmbeddingBatchRepository,
    HumanRetrievalEvaluationRepository,
    IngestionFailureRepository,
    IngestionRepository,
    IngestionRunRepository,
    SemanticSearchRunRepository,
)


class CorpusUnitOfWork(Protocol):
    corpus_activation: CorpusActivationRepository
    corpus_documents: CorpusDocumentRepository
    corpus_chunks: CorpusChunkRepository
    ingestion: IngestionRepository
    ingestion_runs: IngestionRunRepository
    ingestion_failures: IngestionFailureRepository
    embedding_batches: EmbeddingBatchRepository
    semantic_search_runs: SemanticSearchRunRepository
    human_retrieval_evaluations: HumanRetrievalEvaluationRepository

    async def __aenter__(self) -> CorpusUnitOfWork: ...
    async def __aexit__(self, *args: object) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
