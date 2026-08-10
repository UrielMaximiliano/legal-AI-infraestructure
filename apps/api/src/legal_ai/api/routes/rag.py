"""HTTP endpoints for auditable RAG draft generation."""

from __future__ import annotations

import re
import threading
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.ollama.structured_generation import (
    OllamaStructuredGenerationProvider,
)
from legal_ai.adapters.ollama_embedding import OllamaEmbeddingAdapter
from legal_ai.application.draft_service import (
    CaseFileNotFoundError,
    TemplateInactiveError,
    TemplateNotFoundError,
)
from legal_ai.application.inference_coordinator import InferenceCoordinator
from legal_ai.application.rag_generation import (
    RagGenerationError,
    RagGenerationService,
    SQLAlchemyRagAuditStore,
)
from legal_ai.application.rag_retrieval import RagRetrievalService
from legal_ai.config import settings
from legal_ai.domain.errors import DomainError
from legal_ai.schemas.rag import (
    RagDraftGenerationRequest,
    RagDraftGenerationResponse,
    RagDraftSummary,
    RagGenerationSummary,
    RagRetrievalSummary,
    RagRunResponse,
    RagRunSourceResponse,
)

router = APIRouter(tags=["rag"])
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
_coordinator_lock = threading.Lock()
_shared_coordinator: InferenceCoordinator | None = None


class RagRunNotFoundError(DomainError):
    code = "RAG_RUN_NOT_FOUND"
    status_code = 404
    default_message = "La ejecución RAG solicitada no existe"


def rag_idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if value is None or _SAFE_KEY.fullmatch(value) is None:
        raise RagGenerationError("RAG_INVALID_REQUEST")
    return value


def _get_shared_coordinator() -> InferenceCoordinator:
    """Return the process-wide monoslot coordinator used by every RAG request."""

    global _shared_coordinator
    with _coordinator_lock:
        if _shared_coordinator is None:
            _shared_coordinator = InferenceCoordinator(
                max_queue_size=32, wait_timeout=30
            )
        return _shared_coordinator


async def close_rag_coordinator() -> None:
    """Close the shared coordinator during application shutdown only."""

    global _shared_coordinator
    with _coordinator_lock:
        coordinator = _shared_coordinator
        _shared_coordinator = None
    if coordinator is not None:
        await coordinator.close()


def _build_service() -> tuple[RagGenerationService, InferenceCoordinator]:
    coordinator = _get_shared_coordinator()
    embedding = OllamaEmbeddingAdapter(
        base_url=settings.ollama.base_url,
        api_token=settings.ollama.api_token,
        model=settings.embedding.model,
        dimensions=settings.embedding.dimensions,
        timeout_seconds=settings.corpus.embedding_timeout_seconds,
        endpoint=settings.ollama.endpoint,
        context_length=settings.ollama.embedding_context_length,
    )
    retrieval = RagRetrievalService(
        embedding_provider=embedding,
        inference_coordinator=coordinator,
        max_chunks_per_document=settings.rag.max_chunks_per_document,
        max_chunks_per_section=settings.rag.max_chunks_per_section,
    )
    provider = OllamaStructuredGenerationProvider(
        base_url=settings.rag.generation_base_url,
        api_token=settings.rag.generation_token,
        model=settings.rag.generation_model,
        endpoint=settings.rag.generation_endpoint,
        timeout_seconds=settings.rag.generation_timeout_seconds,
        max_retries=settings.rag.generation_max_retries,
    )
    return (
        RagGenerationService(
            retrieval=retrieval,
            provider=provider,
            audit=SQLAlchemyRagAuditStore(),
            prompt_version=settings.rag.prompt_version,
            schema_repair_attempts=settings.rag.schema_repair_attempts,
            inference_coordinator=coordinator,
        ),
        coordinator,
    )


@router.post(
    "/api/v1/rag/drafts/generate",
    response_model=RagDraftGenerationResponse,
    status_code=201,
)
async def generate_rag_draft(
    request: Request,
    response: Response,
    body: RagDraftGenerationRequest,
    idempotency_key: str = Depends(rag_idempotency_key),
) -> RagDraftGenerationResponse:
    async with UnitOfWork() as uow:
        template = await uow.templates.get_by_id(body.template_id)
        if template is None:
            raise TemplateNotFoundError(str(body.template_id))
        if not template.is_active:
            raise TemplateInactiveError(str(body.template_id))
        case_file = await uow.case_files.get_by_id(body.case_file_id)
        if case_file is None:
            raise CaseFileNotFoundError(str(body.case_file_id))
        missing = set(template.variables) - set(body.variables)
        if missing:
            raise RagGenerationError("MISSING_REQUIRED_VARIABLES")
        unexpected = set(body.variables) - set(template.variables)
        if unexpected:
            raise RagGenerationError("RAG_INVALID_REQUEST")

    service, _coordinator = _build_service()
    outcome = await service.generate(
        body,
        idempotency_key=idempotency_key,
        request_id=str(getattr(request.state, "request_id", "")),
    )
    if outcome.draft is None or outcome.structured_draft is None:
        raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
    draft = outcome.draft
    response.status_code = 201
    return RagDraftGenerationResponse(
        request_id=str(getattr(request.state, "request_id", "")),
        rag_run_id=outcome.run.id,
        draft=RagDraftSummary(
            id=draft.id,
            template_id=draft.template_id,
            case_file_id=draft.case_file_id,
            title=draft.title,
            content=draft.content or "",
            status="PENDING_REVIEW",
            version=draft.version,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        ),
        structured_draft=outcome.structured_draft,
        retrieval=RagRetrievalSummary(
            result_count=outcome.run.retrieved_count,
            selected_count=outcome.run.selected_count,
        ),
        generation=RagGenerationSummary(
            model=outcome.run.generation_model,
            prompt_version=outcome.run.prompt_version,
            schema_version=outcome.run.schema_version,
        ),
    )


@router.get("/api/v1/rag/runs/{run_id}", response_model=RagRunResponse)
async def get_rag_run(run_id: UUID) -> RagRunResponse:
    async with UnitOfWork() as uow:
        run = await uow.rag_runs.get(run_id)
        if run is None:
            raise RagRunNotFoundError()
        sources = await uow.rag_sources.list_by_run(run_id)
    return RagRunResponse(
        id=run.id,
        draft_id=run.draft_id,
        case_file_id=run.case_file_id,
        template_id=run.template_id,
        status=str(run.status),
        models={
            "embedding": run.embedding_model,
            "dimensions": run.embedding_dimensions,
            "generation": run.generation_model,
        },
        versions={"prompt": run.prompt_version, "schema": run.schema_version},
        retrieval={"retrieved": run.retrieved_count, "selected": run.selected_count},
        durations_ms={
            "retrieval": run.retrieval_duration_ms,
            "generation": run.generation_duration_ms,
            "validation": run.validation_duration_ms,
            "total": run.total_duration_ms,
        },
        sources=[
            RagRunSourceResponse(
                citation_id=source.citation_id,
                document_id=source.document_id,
                chunk_id=source.chunk_id,
                rank=source.retrieval_rank,
                score=float(source.similarity_score),
                disposition=source.disposition,
            )
            for source in sources
        ],
        error_code=run.error_code,
        request_id=run.request_id,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )
