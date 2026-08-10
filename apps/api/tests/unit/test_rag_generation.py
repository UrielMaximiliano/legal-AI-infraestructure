from __future__ import annotations

from uuid import uuid4

import pytest

from legal_ai.adapters.generation.fake_structured_generation import (
    FakeStructuredGenerationProvider,
)
from legal_ai.application.rag_context import ContextAssembler
from legal_ai.application.rag_generation import (
    InMemoryRagAuditStore,
    RagGenerationError,
    RagGenerationService,
)
from legal_ai.application.rag_retrieval import RagRetrievalResult
from legal_ai.domain.rag import RagRetrievedSource, RagSourceDisposition, sha256_text
from legal_ai.schemas.rag import RagDraftGenerationRequest


class FakeRetrieval:
    async def retrieve(self, query: str, **_: object) -> RagRetrievalResult:
        source = RagRetrievedSource(
            document_id=uuid4(),
            chunk_id=uuid4(),
            external_id="DOC-1",
            title="Reviewed decree",
            publication_date="2025-01-01",
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
            duration_ms=1,
            embedding_model="qwen3-embedding:4b-q4_K_M",
            embedding_dimensions=2560,
        )


@pytest.mark.asyncio
async def test_fake_generation_repairs_once_and_is_idempotent() -> None:
    provider = FakeStructuredGenerationProvider(invalid_attempts=1)
    service = RagGenerationService(retrieval=FakeRetrieval(), provider=provider)
    request = RagDraftGenerationRequest(
        template_id=uuid4(), case_file_id=uuid4(), variables={"cargo": "Director"}
    )
    first = await service.generate(
        request, idempotency_key="rag-test-key-00001", request_id="req-1"
    )
    second = await service.generate(
        request, idempotency_key="rag-test-key-00001", request_id="req-2"
    )
    assert first.run.id == second.run.id
    assert first.run.schema_repair_count == 1
    assert first.draft is not None
    assert first.draft.status.value == "en_revision"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_in_memory_store_rejects_same_key_while_pending() -> None:
    from legal_ai.domain.rag import sha256_text

    store = InMemoryRagAuditStore()
    key_hash = sha256_text("idempotency")
    request_hash = sha256_text("request")
    assert await store.reserve(key_hash, request_hash) is None
    with pytest.raises(RagGenerationError) as exc_info:
        await store.reserve(key_hash, request_hash)
    assert exc_info.value.code == "RAG_GENERATION_IN_PROGRESS"


@pytest.mark.asyncio
async def test_invalid_structured_output_is_repaired_only_once() -> None:
    provider = FakeStructuredGenerationProvider(invalid_attempts=2)
    service = RagGenerationService(retrieval=FakeRetrieval(), provider=provider)
    request = RagDraftGenerationRequest(
        template_id=uuid4(), case_file_id=uuid4(), variables={"cargo": "Director"}
    )
    with pytest.raises(RagGenerationError) as exc_info:
        await service.generate(
            request, idempotency_key="rag-invalid-key-0001", request_id="req-invalid"
        )
    assert exc_info.value.code == "RAG_OUTPUT_INVALID"
    assert provider.calls == 2


class _EmptyRetrieval(FakeRetrieval):
    async def retrieve(self, query: str, **_: object) -> RagRetrievalResult:
        del query
        context = ContextAssembler().assemble(())
        return RagRetrievalResult(
            query_hash=sha256_text("empty"),
            sources=(),
            context=context,
            duration_ms=1,
            embedding_model="qwen3-embedding:4b-q4_K_M",
            embedding_dimensions=2560,
        )


@pytest.mark.asyncio
async def test_insufficient_evidence_never_calls_generation() -> None:
    provider = FakeStructuredGenerationProvider()
    service = RagGenerationService(retrieval=_EmptyRetrieval(), provider=provider)
    request = RagDraftGenerationRequest(template_id=uuid4(), case_file_id=uuid4())
    with pytest.raises(RagGenerationError) as exc_info:
        await service.generate(
            request, idempotency_key="rag-empty-key-0001", request_id="req-empty"
        )
    assert exc_info.value.code == "RAG_INSUFFICIENT_EVIDENCE"
    assert provider.calls == 0


class _FailingAudit(InMemoryRagAuditStore):
    async def save_outcome(self, key_hash: str, outcome) -> None:
        del key_hash, outcome
        raise RuntimeError("audit unavailable")


@pytest.mark.asyncio
async def test_audit_failure_is_fail_closed_after_generation() -> None:
    service = RagGenerationService(
        retrieval=FakeRetrieval(),
        provider=FakeStructuredGenerationProvider(),
        audit=_FailingAudit(),
    )
    request = RagDraftGenerationRequest(template_id=uuid4(), case_file_id=uuid4())
    with pytest.raises(RagGenerationError) as exc_info:
        await service.generate(
            request, idempotency_key="rag-audit-key-0001", request_id="req-audit"
        )
    assert exc_info.value.code == "RAG_AUDIT_UNAVAILABLE"
