from __future__ import annotations

import uuid

import pytest

from legal_ai.schemas.corpus_review import CorpusReviewRequest, CorpusReviewResult


def test_review_dtos_forbid_untrusted_fields() -> None:
    with pytest.raises(ValueError):
        CorpusReviewRequest(
            document_id=uuid.uuid4(),
            approve=True,
            reviewed_by="reviewer",
            expected_version=1,
            raw_content="secret",
        )
    result = CorpusReviewResult(
        document_id=uuid.uuid4(),
        status="REVIEWED",
        review_version=2,
        reviewed_by="reviewer",
        reviewed_at="2026-01-01T00:00:00Z",
    )
    assert "raw_content" not in result.model_dump_json()
    assert "normalized_content" not in result.model_dump_json()
    assert "Authorization" not in result.model_dump_json()
