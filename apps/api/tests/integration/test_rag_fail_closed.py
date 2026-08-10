"""Fail-closed E2E coverage for insufficient or non-reviewable evidence."""

from __future__ import annotations

import pytest

from legal_ai.adapters.generation.fake_structured_generation import (
    FakeStructuredGenerationProvider,
)
from legal_ai.application.rag_context import ContextAssembler
from legal_ai.application.rag_generation import RagGenerationError, RagGenerationService
from legal_ai.application.rag_retrieval import RagRetrievalResult
from legal_ai.domain.rag import sha256_text
from legal_ai.schemas.rag import RagDraftGenerationRequest


class _EmptyRetrieval:
    async def retrieve(self, query: str, **_: object) -> RagRetrievalResult:
        del query
        context = ContextAssembler().assemble(())
        return RagRetrievalResult(
            query_hash=sha256_text("empty-e2e"),
            sources=(),
            context=context,
            duration_ms=0,
            embedding_model="qwen3-embedding:4b-q4_K_M",
            embedding_dimensions=2560,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_reviewable_evidence_creates_no_draft() -> None:
    provider = FakeStructuredGenerationProvider()
    service = RagGenerationService(
        retrieval=_EmptyRetrieval(), provider=provider
    )
    with pytest.raises(RagGenerationError) as exc_info:
        await service.generate(
            RagDraftGenerationRequest(
                template_id="00000000-0000-4000-8000-000000000001",
                case_file_id="00000000-0000-4000-8000-000000000002",
            ),
            idempotency_key="rag-fail-closed-0001",
            request_id="rag-fail-closed",
        )
    assert exc_info.value.code == "RAG_INSUFFICIENT_EVIDENCE"
    assert provider.calls == 0
