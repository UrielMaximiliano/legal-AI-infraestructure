"""Semantic retrieval orchestration with fail-closed audit persistence."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import Callable
from typing import Any

from legal_ai.application.inference_coordinator import InferenceCoordinator
from legal_ai.domain.errors import DomainError, SemanticSearchAuditUnavailableError
from legal_ai.domain.semantic_search import (
    SearchFilters,
    SemanticSearchCandidate,
    SemanticSearchRun,
    SemanticSearchStatus,
)
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from legal_ai.ports.embedding import (
    EmbeddingProvider,
    InferenceCoordinationPort,
    InferencePriority,
)
from legal_ai.schemas.semantic_search import (
    SemanticSearchRequest,
    SemanticSearchResponse,
    SemanticSearchResult,
)


class SemanticSearchProviderUnavailableError(DomainError):
    code = "SEMANTIC_SEARCH_PROVIDER_UNAVAILABLE"
    status_code = 503
    default_message = "El proveedor de embeddings no estÃ¡ disponible"


class SemanticSearchValidationError(DomainError):
    code = "INVALID_SEMANTIC_SEARCH_FILTERS"
    status_code = 422
    default_message = "Los filtros de bÃºsqueda no son vÃ¡lidos"


class SemanticSearchService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], Any],
        embedding_provider: EmbeddingProvider,
        inference_coordinator: InferenceCoordinationPort | None = None,
        model: str = EMBEDDING_MODEL,
        dimensions: int = EMBEDDING_DIMENSIONS,
        audit_retries: int = 1,
        reviewed_only: bool = True,
    ) -> None:
        if model != EMBEDDING_MODEL or dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError("EMBEDDING_CONTRACT_INVALID")
        self._uow_factory = uow_factory
        self._provider = embedding_provider
        self._coordinator = inference_coordinator
        self._model = model
        self._dimensions = dimensions
        self._audit_retries = max(0, audit_retries)
        self._reviewed_only = reviewed_only

    async def search(
        self,
        request: SemanticSearchRequest,
        *,
        request_id: str,
    ) -> SemanticSearchResponse:
        started = time.monotonic()
        normalized_query = " ".join(request.query.split())
        if not normalized_query:
            raise SemanticSearchValidationError()
        query_hash = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()
        try:
            filters = SearchFilters(
                document_type=request.document_type,
                document_subtype=request.document_subtype,
                jurisdiction=request.jurisdiction,
                language=request.language,
                organization=request.organization,
                review_status=request.review_status,
                reviewed_only=self._reviewed_only,
            )
        except ValueError as exc:
            raise SemanticSearchValidationError() from exc
        coordinator = self._coordinator or InferenceCoordinator(
            max_queue_size=1, wait_timeout=10
        )
        try:

            async def embed_query() -> list[float]:
                return await self._provider.embed_query(normalized_query)

            query_vector = await coordinator.execute(
                InferencePriority.SEARCH, embed_query, timeout=10
            )
            async with self._uow_factory() as uow:
                candidates = await uow.vector_search.search(
                    query_vector,
                    filters=filters,
                    top_k=request.top_k,
                    minimum_score=request.minimum_score,
                    reviewed_only=self._reviewed_only,
                )
            results = tuple(
                SemanticSearchResult(
                    document_id=str(candidate.document_id),
                    chunk_id=str(candidate.chunk_id),
                    external_id=candidate.external_id,
                    source_name=candidate.source_name,
                    title=candidate.title,
                    document_type=candidate.document_type,
                    document_subtype=candidate.document_subtype,
                    jurisdiction=candidate.jurisdiction,
                    language=candidate.language,
                    organization=candidate.organization,
                    section_type=candidate.section_type,
                    article_number=candidate.article_number,
                    excerpt=candidate.excerpt,
                    chunk_index=candidate.chunk_index,
                    similarity_score=candidate.similarity_score,
                    generation=candidate.generation,
                    publication_date=candidate.publication_date,
                    source_url=candidate.source_url,
                    metadata=candidate.metadata,
                    embedding_model=self._model,
                    embedding_dimensions=self._dimensions,
                )
                for candidate in candidates
                if isinstance(candidate, SemanticSearchCandidate)
            )
            run = SemanticSearchRun(
                id=uuid.uuid4(),
                query_hash=query_hash,
                filters_sanitized=filters.sanitized(),
                top_k=request.top_k,
                minimum_score=request.minimum_score,
                embedding_model=self._model,
                embedding_dimensions=self._dimensions,
                result_count=len(results),
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                status=SemanticSearchStatus.SUCCEEDED,
                request_id=request_id,
            )
            await self._audit(run)
            return SemanticSearchResponse(
                request_id=request_id,
                result_count=len(results),
                results=results,
            )
        except SemanticSearchAuditUnavailableError:
            raise
        except DomainError:
            raise
        except Exception as exc:
            error_code = getattr(exc, "code", None)
            if not isinstance(error_code, str) or not error_code:
                error_code = "SEMANTIC_SEARCH_PROVIDER_UNAVAILABLE"
            failed_run = SemanticSearchRun(
                id=uuid.uuid4(),
                query_hash=query_hash,
                filters_sanitized=filters.sanitized(),
                top_k=request.top_k,
                minimum_score=request.minimum_score,
                embedding_model=self._model,
                embedding_dimensions=self._dimensions,
                result_count=0,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                status=SemanticSearchStatus.FAILED,
                request_id=request_id,
                error_code=error_code,
            )
            try:
                await self._audit(failed_run)
            except SemanticSearchAuditUnavailableError:
                raise
            raise SemanticSearchProviderUnavailableError() from exc
        finally:
            if self._coordinator is None and hasattr(coordinator, "close"):
                await coordinator.close()

    async def _audit(self, run: SemanticSearchRun) -> None:
        last_error: Exception | None = None
        for attempt in range(self._audit_retries + 1):
            try:
                async with self._uow_factory() as uow:
                    await uow.semantic_search_runs.create(run)
                return
            except Exception as exc:  # fail closed, never return partial results
                last_error = exc
                if attempt < self._audit_retries:
                    await asyncio.sleep(0.05 * (2**attempt))
        raise SemanticSearchAuditUnavailableError() from last_error
