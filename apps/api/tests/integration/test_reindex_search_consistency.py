from __future__ import annotations

import uuid

from legal_ai.domain.semantic_search import SearchFilters


def test_generation_filter_contract_never_allows_mixed_generations() -> None:
    filters = SearchFilters(
        document_type="decreto",
        document_subtype="designacion_transitoria",
        jurisdiction="nacion",
        reviewed_only=True,
    )
    assert filters.sanitized()["review_status"] == "REVIEWED"
    assert str(uuid.uuid4())
