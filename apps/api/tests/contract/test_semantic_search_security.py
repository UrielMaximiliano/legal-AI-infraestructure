from __future__ import annotations

import uuid

import pytest

from legal_ai.domain.semantic_search import (
    SearchFilters,
    SemanticSearchRun,
    SemanticSearchStatus,
)
from legal_ai.schemas.semantic_search import (
    SemanticSearchResponse,
    SemanticSearchResult,
)


def test_search_filters_fail_closed_for_sensitive_keys() -> None:
    with pytest.raises(ValueError, match="INVALID_SEMANTIC_SEARCH_FILTERS"):
        SearchFilters(
            document_type="decreto",
            document_subtype="designacion_transitoria",
            jurisdiction="nacion",
            organization="Authorization Bearer secret",
        )


def test_search_run_and_response_have_no_sensitive_fields() -> None:
    run = SemanticSearchRun(
        id=uuid.uuid4(),
        query_hash="a" * 64,
        filters_sanitized={
            "document_type": "decreto",
            "document_subtype": "designacion_transitoria",
            "jurisdiction": "nacion",
            "review_status": "REVIEWED",
        },
        top_k=3,
        minimum_score=None,
        embedding_model="qwen3-embedding:4b-q4_K_M",
        embedding_dimensions=2560,
        result_count=0,
        duration_ms=1,
        status=SemanticSearchStatus.SUCCEEDED,
        request_id="request-id",
    )
    result = SemanticSearchResult(
        document_id=str(uuid.uuid4()),
        chunk_id=str(uuid.uuid4()),
        external_id="doc",
        source_name="filesystem",
        document_type="decreto",
        document_subtype="designacion_transitoria",
        jurisdiction="nacion",
        language="es",
        organization=None,
        section_type="ARTICLE",
        article_number="1",
        excerpt="excerpt",
        chunk_index=0,
        similarity_score=1.0,
        generation=1,
    )
    response = SemanticSearchResponse(
        request_id="request-id", result_count=1, results=(result,)
    )
    payload = response.model_dump_json()
    assert "raw_content" not in payload
    assert "normalized_content" not in payload
    assert '"embedding":[' not in payload
    assert "Authorization" not in payload
    assert run.query_hash == "a" * 64
