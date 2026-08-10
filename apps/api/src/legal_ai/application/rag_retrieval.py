"""Reusable exact retrieval for semantic search and RAG."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.inference_coordinator import (
    InferenceCoordinator,
)
from legal_ai.application.rag_context import ContextAssembler, RagContext
from legal_ai.domain.rag import (
    RagRetrievedSource,
    RagSourceDisposition,
    citation_id,
    sha256_text,
)
from legal_ai.domain.semantic_search import SemanticSearchCandidate
from legal_ai.ports.embedding import EmbeddingProvider, InferencePriority


@dataclass(frozen=True, slots=True)
class RagRetrievalResult:
    query_hash: str
    sources: tuple[RagRetrievedSource, ...]
    context: RagContext
    duration_ms: int
    embedding_model: str
    embedding_dimensions: int


class RagRetrievalService:
    """Retrieve only reviewed INDEX_90 active chunks and diversify deterministically."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], UnitOfWork] = UnitOfWork,
        embedding_provider: EmbeddingProvider,
        inference_coordinator: InferenceCoordinator | None = None,
        context_assembler: ContextAssembler | None = None,
        embedding_model: str = "qwen3-embedding:4b-q4_K_M",
        embedding_dimensions: int = 2560,
        max_chunks_per_document: int = 2,
        max_chunks_per_section: int = 1,
    ) -> None:
        if (
            embedding_model != "qwen3-embedding:4b-q4_K_M"
            or embedding_dimensions != 2560
        ):
            raise ValueError("RAG_EMBEDDING_CONTRACT_INVALID")
        self._uow_factory = uow_factory
        self._embedding_provider = embedding_provider
        self._coordinator = inference_coordinator
        self._context_assembler = context_assembler or ContextAssembler()
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.max_chunks_per_document = max(1, max_chunks_per_document)
        self.max_chunks_per_section = max(1, max_chunks_per_section)

    @staticmethod
    def _candidate_key(
        candidate: SemanticSearchCandidate,
    ) -> tuple[float, str, str, int, str, str]:
        return (
            -candidate.similarity_score,
            candidate.publication_date or "",
            str(candidate.document_id),
            candidate.chunk_index,
            candidate.section_type,
            str(candidate.chunk_id),
        )

    def _select(
        self,
        candidates: Sequence[SemanticSearchCandidate],
        *,
        minimum_score: float,
    ) -> tuple[RagRetrievedSource, ...]:
        ordered = sorted(candidates, key=self._candidate_key)
        document_counts: defaultdict[uuid.UUID, int] = defaultdict(int)
        section_counts: defaultdict[tuple[uuid.UUID, str], int] = defaultdict(int)
        sources: list[RagRetrievedSource] = []
        selected_count = 0
        for rank, candidate in enumerate(ordered, start=1):
            disposition = RagSourceDisposition.SELECTED
            if candidate.similarity_score < minimum_score:
                disposition = RagSourceDisposition.EXCLUDED_SCORE
            elif document_counts[
                candidate.document_id
            ] >= self.max_chunks_per_document or (
                section_counts[(candidate.document_id, candidate.section_type)]
                >= self.max_chunks_per_section
            ):
                disposition = RagSourceDisposition.EXCLUDED_DIVERSITY
            else:
                document_counts[candidate.document_id] += 1
                section_counts[(candidate.document_id, candidate.section_type)] += 1
                selected_count += 1
            metadata = candidate.metadata
            content_hash = candidate.content_hash
            if not isinstance(content_hash, str) or len(content_hash) != 64:
                content_hash = sha256_text(candidate.excerpt)
            sources.append(
                RagRetrievedSource(
                    document_id=candidate.document_id,
                    chunk_id=candidate.chunk_id,
                    external_id=candidate.external_id,
                    title=candidate.title or candidate.source_name,
                    publication_date=candidate.publication_date,
                    section_type=candidate.section_type,
                    generation=candidate.generation,
                    similarity_score=candidate.similarity_score,
                    retrieval_rank=rank,
                    citation_id=citation_id(rank),
                    excerpt=candidate.excerpt,
                    article_number=candidate.article_number,
                    source_url=candidate.source_url,
                    disposition=disposition,
                    context_rank=(
                        selected_count
                        if disposition is RagSourceDisposition.SELECTED
                        else None
                    ),
                    content_hash=content_hash,
                    metadata=metadata,
                )
            )
        return tuple(sources)

    async def retrieve(
        self,
        query: str,
        *,
        filters: dict[str, str],
        top_k: int = 8,
        candidate_pool_size: int | None = None,
        minimum_score: float = 0.0,
    ) -> RagRetrievalResult:
        started = time.monotonic()
        normalized_query = " ".join(query.split())
        if not normalized_query or not 3 <= top_k <= 20:
            raise ValueError("RAG_RETRIEVAL_REQUEST_INVALID")
        if (
            filters.get("evaluation_split") != "INDEX_90"
            or filters.get("review_status") != "REVIEWED"
        ):
            raise ValueError("RAG_CORPUS_POLICY_INVALID")
        pool_size = candidate_pool_size or min(3 * top_k, 50)
        if not top_k <= pool_size <= 50:
            raise ValueError("RAG_RETRIEVAL_LIMIT_INVALID")
        coordinator = self._coordinator or InferenceCoordinator(
            max_queue_size=1, wait_timeout=30
        )
        try:

            async def embed() -> list[float]:
                return await self._embedding_provider.embed_query(normalized_query)

            query_vector = await coordinator.execute(
                InferencePriority.SEARCH, embed, timeout=30
            )
            async with self._uow_factory() as uow:
                candidates = await uow.vector_search.search(
                    query_vector,
                    filters=filters,
                    top_k=pool_size,
                    minimum_score=minimum_score,
                    reviewed_only=True,
                    evaluation_split="INDEX_90",
                )
            typed = tuple(
                candidate
                for candidate in candidates
                if isinstance(candidate, SemanticSearchCandidate)
            )
            sources = self._select(typed, minimum_score=minimum_score)
            context = self._context_assembler.assemble(sources)
            return RagRetrievalResult(
                query_hash=sha256_text(normalized_query),
                sources=context.sources,
                context=context,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                embedding_model=self.embedding_model,
                embedding_dimensions=self.embedding_dimensions,
            )
        finally:
            if self._coordinator is None:
                await coordinator.close()
