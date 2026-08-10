from __future__ import annotations

import pytest

from legal_ai.application.rag_query import RagQueryBuilder
from legal_ai.observability.rag import sanitize_rag_event


def test_query_builder_is_allowlisted_and_hashable() -> None:
    result = RagQueryBuilder().build(
        case_file={"matter": "designation"},
        template={"kind": "decree"},
        variables={"cargo": "Director"},
        organization="Ministerio",
        language="ES",
    )
    assert result.query_hash
    assert result.filters["evaluation_split"] == "INDEX_90"
    assert result.filters["review_status"] == "REVIEWED"
    assert "authorization" not in result.text.lower()


def test_query_builder_fails_closed_without_data() -> None:
    with pytest.raises(ValueError, match="RAG_QUERY_EMPTY"):
        RagQueryBuilder().build()


def test_rag_telemetry_drops_sensitive_and_non_scalar_values() -> None:
    result = sanitize_rag_event(
        {
            "request_id": "req-1",
            "selected_count": 2,
            "prompt": "secret prompt",
            "query": "secret query",
            "vector": [0.1],
            "nested": {"secret": True},
        }
    )
    assert result == {"request_id": "req-1", "selected_count": 2}
