from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from legal_ai.application.corpus_review import CorpusReviewService
from legal_ai.domain.corpus import ReviewStatus, sha256_text
from legal_ai.schemas.corpus_review import CorpusReviewRequest


def _request(*, approve: bool = True, reason: str | None = None) -> CorpusReviewRequest:
    return CorpusReviewRequest(
        document_id=uuid.uuid4(),
        approve=approve,
        reject=not approve,
        reason=reason,
        reviewed_by="reviewer",
        expected_version=1,
    )


def test_review_request_requires_one_decision_and_reason_for_rejection() -> None:
    with pytest.raises(ValueError, match="DECISION"):
        CorpusReviewRequest(
            document_id=uuid.uuid4(),
            reviewed_by="reviewer",
            expected_version=1,
        )
    with pytest.raises(ValueError, match="REASON"):
        _request(approve=False)
    with pytest.raises(ValueError, match="NOT_ALLOWED"):
        _request(reason="not allowed")


@pytest.mark.asyncio
async def test_review_service_returns_only_safe_fields() -> None:
    class Document:
        reviewed_by = "reviewer"
        reviewed_at = datetime.now(UTC)
        review_status = ReviewStatus.REVIEWED
        review_version = 2
        id = uuid.uuid4()

    class Repository:
        async def compare_and_swap_review(self, *args, **kwargs):
            return Document()

    class Uow:
        corpus_documents = Repository()

    result = await CorpusReviewService(Uow()).review(
        _request(), request_id="review-request"
    )
    assert result.model_dump().keys() == {
        "document_id",
        "status",
        "review_version",
        "reviewed_by",
        "reviewed_at",
        "request_id",
    }
    assert "raw_content" not in result.model_dump_json()


def test_review_domain_hash_fixture_is_deterministic() -> None:
    assert sha256_text("legal") == sha256_text("legal")
