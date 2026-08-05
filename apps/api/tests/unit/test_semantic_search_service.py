from __future__ import annotations

import uuid

import pytest

from legal_ai.adapters.embeddings.fake_embedding import FakeEmbeddingProvider
from legal_ai.application.semantic_search import (
    SemanticSearchAuditUnavailableError,
    SemanticSearchProviderUnavailableError,
    SemanticSearchService,
)
from legal_ai.domain.semantic_search import SemanticSearchCandidate
from legal_ai.schemas.semantic_search import SemanticSearchRequest


class _Repo:
    def __init__(self, *, fail: bool = False) -> None:
        self.runs = []
        self.fail = fail

    async def create(self, run):
        if self.fail:
            raise RuntimeError("audit database unavailable")
        self.runs.append(run)


class _Uow:
    def __init__(self, *, fail_audit: bool = False) -> None:
        self.semantic_search_runs = _Repo(fail=fail_audit)
        self.vector_search = self
        self.result = SemanticSearchCandidate(
            document_id=uuid.uuid4(),
            chunk_id=uuid.uuid4(),
            external_id="doc-1",
            source_name="filesystem",
            document_type="decreto",
            document_subtype="designacion_transitoria",
            jurisdiction="nacion",
            language="es",
            section_type="ARTICLE",
            article_number="1",
            excerpt="Texto breve",
            chunk_index=0,
            similarity_score=0.9,
            generation=1,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def search(self, *args, **kwargs):
        return (self.result,)


@pytest.mark.asyncio
async def test_search_audits_before_returning_and_redacts_query() -> None:
    uow = _Uow()
    service = SemanticSearchService(
        uow_factory=lambda: uow,
        embedding_provider=FakeEmbeddingProvider(),
    )
    response = await service.search(
        SemanticSearchRequest(
            query="consulta jurídica privada",
            document_type="decreto",
            document_subtype="designacion_transitoria",
            jurisdiction="nacion",
        ),
        request_id="request-1",
    )
    assert response.result_count == 1
    assert response.results[0].excerpt == "Texto breve"
    assert len(uow.semantic_search_runs.runs) == 1
    assert uow.semantic_search_runs.runs[0].query_hash
    assert "consulta" not in str(uow.semantic_search_runs.runs[0].filters_sanitized)


@pytest.mark.asyncio
async def test_search_is_fail_closed_when_audit_is_unavailable() -> None:
    uow = _Uow(fail_audit=True)
    service = SemanticSearchService(
        uow_factory=lambda: uow,
        embedding_provider=FakeEmbeddingProvider(),
        audit_retries=0,
    )
    with pytest.raises(SemanticSearchAuditUnavailableError):
        await service.search(
            SemanticSearchRequest(
                query="consulta",
                document_type="decreto",
                document_subtype="designacion_transitoria",
                jurisdiction="nacion",
            ),
            request_id="request-2",
        )


@pytest.mark.asyncio
async def test_provider_failure_is_audited_as_failed_without_payload() -> None:
    class Provider(FakeEmbeddingProvider):
        async def embed_query(self, text: str):
            raise RuntimeError("secret vector and query")

    uow = _Uow()
    service = SemanticSearchService(
        uow_factory=lambda: uow,
        embedding_provider=Provider(),
        audit_retries=0,
    )
    with pytest.raises(SemanticSearchProviderUnavailableError):
        await service.search(
            SemanticSearchRequest(
                query="consulta",
                document_type="decreto",
                document_subtype="designacion_transitoria",
                jurisdiction="nacion",
            ),
            request_id="request-failed",
        )
    assert len(uow.semantic_search_runs.runs) == 1
    assert uow.semantic_search_runs.runs[0].status.value == "FAILED"
    assert uow.semantic_search_runs.runs[0].error_code


def test_search_request_accepts_documented_nested_filter_envelope() -> None:
    request = SemanticSearchRequest(
        query="designacion",
        filters={
            "document_type": "decreto",
            "document_subtype": "designacion_transitoria",
            "jurisdiction": "nacion",
        },
    )
    assert request.document_type == "decreto"
    assert request.document_subtype == "designacion_transitoria"
    assert request.jurisdiction == "nacion"
