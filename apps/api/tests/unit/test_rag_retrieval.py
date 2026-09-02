from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from legal_ai.adapters.embeddings.fake_embedding import FakeEmbeddingProvider
from legal_ai.application.rag_retrieval import RagRetrievalService
from legal_ai.domain.rag import RagSourceDisposition, sha256_text
from legal_ai.domain.semantic_search import SemanticSearchCandidate


def _candidate(
    *, document_id, score: float, section: str, index: int
) -> SemanticSearchCandidate:
    content = f"Evidence {index}"
    return SemanticSearchCandidate(
        document_id=document_id,
        chunk_id=uuid4(),
        external_id=f"DOC-{index}",
        source_name="fixture",
        title="Reviewed decree",
        document_type="decreto",
        document_subtype="designacion_transitoria",
        jurisdiction="nacion",
        language="es",
        section_type=section,
        article_number=None,
        excerpt=content,
        chunk_index=index,
        similarity_score=score,
        generation=1,
        publication_date=date(2025, 1, index + 1).isoformat(),
        content_hash=sha256_text(content),
    )


class _VectorSearch:
    def __init__(self, candidates: tuple[SemanticSearchCandidate, ...]) -> None:
        self.candidates = candidates
        self.filters: dict[str, str] | None = None

    async def search(self, vector, **kwargs):
        del vector
        self.filters = kwargs["filters"]
        return self.candidates


class _Uow:
    def __init__(self, search: _VectorSearch) -> None:
        self.vector_search = search

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback


@pytest.mark.asyncio
async def test_retrieval_is_reviewed_index90_and_diversified() -> None:
    first_document = uuid4()
    second_document = uuid4()
    candidates = (
        _candidate(
            document_id=first_document, score=0.9, section="CONSIDERANDO", index=0
        ),
        _candidate(
            document_id=first_document, score=0.8, section="CONSIDERANDO", index=1
        ),
        _candidate(
            document_id=second_document, score=0.7, section="VISTO", index=2
        ),
    )
    vector_search = _VectorSearch(candidates)

    def uow_factory() -> _Uow:
        return _Uow(vector_search)

    service = RagRetrievalService(
        uow_factory=uow_factory,
        embedding_provider=FakeEmbeddingProvider(),
        max_chunks_per_document=1,
        max_chunks_per_section=1,
    )
    result = await service.retrieve(
        "designacion transitoria",
        filters={
            "document_type": "decreto",
            "document_subtype": "designacion_transitoria",
            "jurisdiction": "nacion",
            "review_status": "REVIEWED",
            "evaluation_split": "INDEX_90",
        },
        top_k=3,
        candidate_pool_size=3,
        minimum_score=0.0,
    )

    assert result.embedding_dimensions == 2560
    assert result.sources[0].disposition is RagSourceDisposition.SELECTED
    assert result.sources[0].content_hash == sha256_text("Evidence 0")
    assert result.sources[1].disposition is RagSourceDisposition.EXCLUDED_DIVERSITY
    assert result.sources[2].disposition is RagSourceDisposition.SELECTED
    assert (
        result.context.sources[1].disposition
        is RagSourceDisposition.EXCLUDED_DIVERSITY
    )
    assert vector_search.filters["evaluation_split"] == "INDEX_90"


@pytest.mark.asyncio
async def test_retrieval_never_selects_more_than_top_k() -> None:
    candidates = tuple(
        _candidate(
            document_id=uuid4(),
            score=0.9 - (index * 0.01),
            section="CONSIDERANDO",
            index=index,
        )
        for index in range(6)
    )
    vector_search = _VectorSearch(candidates)

    service = RagRetrievalService(
        uow_factory=lambda: _Uow(vector_search),
        embedding_provider=FakeEmbeddingProvider(),
        max_chunks_per_document=2,
        max_chunks_per_section=2,
    )
    result = await service.retrieve(
        "mantenimiento de computadoras",
        filters={
            "document_type": "decreto",
            "jurisdiction": "nacion",
            "review_status": "REVIEWED",
            "evaluation_split": "INDEX_90",
        },
        top_k=3,
        candidate_pool_size=6,
        minimum_score=0.0,
    )

    assert sum(
        source.disposition is RagSourceDisposition.SELECTED
        for source in result.sources
    ) == 3


@pytest.mark.asyncio
async def test_retrieval_rejects_unapproved_corpus_policy() -> None:
    service = RagRetrievalService(
        embedding_provider=FakeEmbeddingProvider(),
    )
    with pytest.raises(ValueError, match="RAG_CORPUS_POLICY_INVALID"):
        await service.retrieve(
            "query",
            filters={
                "document_type": "decreto",
                "document_subtype": "designacion_transitoria",
                "jurisdiction": "nacion",
                "review_status": "REVIEWED",
                "evaluation_split": "HOLDOUT_10",
            },
        )
