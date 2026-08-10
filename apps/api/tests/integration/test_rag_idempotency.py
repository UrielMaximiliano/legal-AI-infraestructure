"""Idempotency and concurrent request evidence with the in-memory audit fake."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from legal_ai.adapters.generation.fake_structured_generation import (
    FakeStructuredGenerationProvider,
)
from legal_ai.application.rag_context import ContextAssembler
from legal_ai.application.rag_generation import RagGenerationError, RagGenerationService
from legal_ai.application.rag_retrieval import RagRetrievalResult
from legal_ai.domain.rag import RagRetrievedSource, RagSourceDisposition, sha256_text
from legal_ai.schemas.rag import RagDraftGenerationRequest


class _Retrieval:
    async def retrieve(self, query: str, **_: object) -> RagRetrievalResult:
        source = RagRetrievedSource(
            document_id=uuid4(),
            chunk_id=uuid4(),
            external_id="IDEMPOTENCY-TEST",
            title="Reviewed test source",
            publication_date=None,
            section_type="CONSIDERANDO",
            generation=1,
            similarity_score=0.9,
            retrieval_rank=1,
            citation_id="SRC-001",
            excerpt="Reviewed evidence",
            disposition=RagSourceDisposition.SELECTED,
            context_rank=1,
            content_hash=sha256_text("Reviewed evidence"),
        )
        context = ContextAssembler().assemble((source,))
        return RagRetrievalResult(
            query_hash=sha256_text(query),
            sources=context.sources,
            context=context,
            duration_ms=0,
            embedding_model="qwen3-embedding:4b-q4_K_M",
            embedding_dimensions=2560,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_same_key_concurrent_requests_have_one_winner() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingProvider(FakeStructuredGenerationProvider):
        async def generate_structured(self, **kwargs):
            started.set()
            await release.wait()
            return await super().generate_structured(**kwargs)

    service = RagGenerationService(
        retrieval=_Retrieval(), provider=_BlockingProvider()
    )
    request = RagDraftGenerationRequest(
        template_id=uuid4(), case_file_id=uuid4(), variables={"cargo": "Director"}
    )
    first_task = asyncio.create_task(
        service.generate(
            request, idempotency_key="rag-concurrent-0001", request_id="r1"
        )
    )
    await started.wait()
    with pytest.raises(RagGenerationError) as exc_info:
        await service.generate(
            request, idempotency_key="rag-concurrent-0001", request_id="r2"
        )
    release.set()
    await first_task
    assert exc_info.value.code == "RAG_GENERATION_IN_PROGRESS"
