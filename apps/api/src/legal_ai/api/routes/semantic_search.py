"""Semantic search endpoint for the 005 MVP."""

from __future__ import annotations

from fastapi import APIRouter, Request

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.ollama_embedding import OllamaEmbeddingAdapter
from legal_ai.application.semantic_search import SemanticSearchService
from legal_ai.config import settings
from legal_ai.schemas.semantic_search import (
    SemanticSearchRequest,
    SemanticSearchResponse,
)

router = APIRouter(prefix="/api/v1", tags=["semantic-search"])


def _service() -> SemanticSearchService:
    provider = OllamaEmbeddingAdapter(
        base_url=settings.ollama.base_url,
        api_token=settings.ollama.api_token,
        model=settings.embedding.model,
        dimensions=settings.embedding.dimensions,
        timeout_seconds=settings.ollama.timeout_seconds,
        endpoint=settings.ollama.endpoint,
    )
    return SemanticSearchService(
        uow_factory=UnitOfWork,
        embedding_provider=provider,
        model=settings.embedding.model,
        dimensions=settings.embedding.dimensions,
    )


@router.post("/semantic-search", response_model=SemanticSearchResponse)
async def semantic_search(
    payload: SemanticSearchRequest, request: Request
) -> SemanticSearchResponse:
    return await _service().search(
        payload,
        request_id=str(request.state.request_id),
    )
