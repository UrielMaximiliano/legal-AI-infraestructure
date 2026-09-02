"""Controllers for liveness, readiness and dependency health checks."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from legal_ai.adapters.database.dispositions_rag_unit_of_work import (
    DispositionsRagUnitOfWork,
)
from legal_ai.adapters.database.engine import get_engine
from legal_ai.adapters.database.health import PostgreSQLHealthAdapter
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.ollama.client import create_ollama_client
from legal_ai.adapters.ollama.health import OllamaHealthAdapter
from legal_ai.application.health_service import HealthService
from legal_ai.config import settings
from legal_ai.schemas.health import (
    DependencyHealthSchema,
    HealthDependenciesResponse,
    HealthLiveResponse,
    HealthReadyResponse,
    RagGenerationReadiness,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


def _get_health_service() -> HealthService:
    profile = settings.rag_profile
    database = (
        "imi_dispositions_rag" if profile.code == "imi_leg_06b" else "legacy"
    )
    db_adapter = PostgreSQLHealthAdapter(get_engine(database))
    client = create_ollama_client()
    ollama_adapter = OllamaHealthAdapter(
        client,
        expected_model=profile.embedding_model,
        expected_dimensions=profile.embedding_dimensions,
    )
    return HealthService(db_adapter, ollama_adapter)


async def _rag_generation_readiness() -> RagGenerationReadiness:
    """Report configuration and the effective reviewed INDEX_90 corpus.

    The readiness probe checks whether the operational split exists. The
    generation request applies its own validated taxonomy filters later.
    """

    try:
        ollama = settings.ollama
        available = bool(ollama.base_url and ollama.api_token)
    except (ValueError, RuntimeError):
        available = False
    eligible = 0
    corpus_error: str | None = None
    if available:
        try:
            if settings.rag_profile.code == "imi_leg_06b":
                async with DispositionsRagUnitOfWork() as uow:
                    result = await uow.session.execute(
                        text(
                            """
                            SELECT count(DISTINCT d.id)
                            FROM rag.corpus_documents d
                            JOIN rag.corpus_document_versions v
                              ON v.document_id = d.id
                            JOIN rag.corpus_chunks c
                              ON c.document_version_id = v.id
                            WHERE d.active AND v.is_active
                              AND v.review_status_code = 'REVIEWED'
                              AND c.state_code = 'ACTIVE'
                              AND c.embedding IS NOT NULL
                              AND EXISTS (
                                SELECT 1 FROM rag.corpus_document_version_splits s
                                WHERE s.document_version_id = v.id
                                  AND s.split_code = :split
                              )
                            """
                        ),
                        {"split": settings.rag.required_evaluation_split},
                    )
                    eligible = int(result.scalar_one())
            else:
                async with UnitOfWork() as uow:
                    eligible = (
                        await uow.corpus_documents.count_eligible_reviewed_documents(
                            evaluation_split=settings.rag.required_evaluation_split
                        )
                    )
        except Exception:
            logger.warning("RAG corpus readiness query failed", exc_info=True)
            corpus_error = "RAG_CORPUS_UNAVAILABLE"
    status = "unavailable"
    error_code: str | None = "OLLAMA_CONFIGURATION_INVALID"
    if available and corpus_error is None:
        status = "ready" if eligible > 0 else "not_ready"
        error_code = None if eligible > 0 else "RAG_NO_REVIEWED_INDEX_90_DOCUMENTS"
    elif available:
        error_code = corpus_error
    profile = settings.rag_profile
    return RagGenerationReadiness(
        status=status,
        generation_model=profile.generation_model,
        embedding_model=profile.embedding_model,
        dimensions=profile.embedding_dimensions,
        eligible_reviewed_documents=eligible,
        error_code=error_code,
        profile_code=profile.code,
        rag_database=profile.rag_database_name,
        core_database=profile.core_database_name,
        embedding_context_length=profile.embedding_context_length,
        rag_context_length=profile.rag_context_length,
        generation_context_length=profile.generation_context_length,
    )


@router.get("/health/live", response_model=HealthLiveResponse)
async def health_live(request: Request) -> HealthLiveResponse:
    return HealthLiveResponse(
        status="ok",
        service=settings.app.name,
        version=settings.app.version,
        request_id=request.state.request_id,
    )


@router.get("/health/ready", response_model=HealthReadyResponse)
async def health_ready(request: Request, response: Response) -> HealthReadyResponse:
    service = _get_health_service()
    try:
        result = await service.check_all()
        readiness = service.compute_readiness(result)
        if readiness != "ready":
            response.status_code = 503
        return HealthReadyResponse(
            status=readiness,
            timestamp=service.now_utc(),
            request_id=request.state.request_id,
            rag_generation=await _rag_generation_readiness(),
        )
    except Exception:
        logger.exception("Internal health readiness failure")
        response.status_code = 500
        return HealthReadyResponse(
            status="not_ready",
            timestamp=service.now_utc(),
            request_id=request.state.request_id,
            rag_generation=await _rag_generation_readiness(),
        )


@router.get("/health/dependencies", response_model=HealthDependenciesResponse)
async def health_dependencies(
    request: Request, response: Response
) -> HealthDependenciesResponse:
    service = _get_health_service()
    try:
        result = await service.check_all()
        aggregate = service.compute_aggregate_status(result)
        return HealthDependenciesResponse(
            status=aggregate.value,
            timestamp=service.now_utc(),
            request_id=request.state.request_id,
            dependencies={
                "postgres": DependencyHealthSchema(
                    status=result.postgres.status.value,
                    latency_ms=result.postgres.latency_ms,
                    error_code=result.postgres.error_code,
                    message=result.postgres.message,
                ),
                "pgvector": DependencyHealthSchema(
                    status=result.pgvector.status.value,
                    latency_ms=result.pgvector.latency_ms,
                    error_code=result.pgvector.error_code,
                    message=result.pgvector.message,
                ),
                "ollama": DependencyHealthSchema(
                    status=result.ollama.status.value,
                    latency_ms=result.ollama.latency_ms,
                    error_code=result.ollama.error_code,
                    message=result.ollama.message,
                ),
                "semantic_retrieval": DependencyHealthSchema(
                    status=(
                        result.semantic_retrieval.status.value
                        if result.semantic_retrieval is not None
                        else result.ollama.status.value
                    ),
                    latency_ms=(
                        result.semantic_retrieval.latency_ms
                        if result.semantic_retrieval is not None
                        else result.ollama.latency_ms
                    ),
                    error_code=(
                        result.semantic_retrieval.error_code
                        if result.semantic_retrieval is not None
                        else result.ollama.error_code
                    ),
                    message=(
                        result.semantic_retrieval.message
                        if result.semantic_retrieval is not None
                        else result.ollama.message
                    ),
                ),
            },
        )
    except Exception:
        logger.exception("Internal health dependencies failure")
        response.status_code = 500
        return HealthDependenciesResponse(
            status="error",
            timestamp=service.now_utc(),
            request_id=request.state.request_id,
            dependencies={
                name: DependencyHealthSchema(
                    status="unavailable",
                    error_code="INTERNAL_DIAGNOSTIC_ERROR",
                    message="Internal diagnostic error",
                )
                for name in ("postgres", "pgvector", "ollama")
            },
        )
