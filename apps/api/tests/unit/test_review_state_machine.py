"""Review transition and comment invariants."""

from datetime import UTC, datetime
from uuid import uuid4

from legal_ai.domain.enums import CommentSeverity, CommentStatus, ReviewStatus
from legal_ai.domain.review import DocumentReview
from legal_ai.domain.review_comment import ReviewComment


def _review(status: ReviewStatus = ReviewStatus.OPEN) -> DocumentReview:
    now = datetime.now(UTC)
    return DocumentReview(
        id=uuid4(),
        draft_id=uuid4(),
        draft_version=1,
        review_snapshot={"draft_version": 1},
        review_snapshot_sha256="a" * 64,
        status=status,
        opened_by="reviewer",
        version=1,
        opened_at=now,
        created_at=now,
        updated_at=now,
    )


def test_review_closes_only_at_closed_status() -> None:
    assert not _review().is_closed()
    assert _review(ReviewStatus.CLOSED).is_closed()


def test_blocking_comment_is_open_only_in_open_state() -> None:
    now = datetime.now(UTC)
    comment = ReviewComment(
        id=uuid4(),
        review_id=uuid4(),
        draft_version=1,
        author="reviewer",
        severity=CommentSeverity.BLOCKING,
        status=CommentStatus.OPEN,
        body="Resolve this point",
        version=1,
        created_at=now,
        updated_at=now,
    )
    assert comment.is_open_blocking()
    comment.status = CommentStatus.RESOLVED
    assert not comment.is_open_blocking()


def test_review_snapshot_is_not_replaced_by_state_helpers() -> None:
    review = _review()
    original = dict(review.review_snapshot)
    review.status = ReviewStatus.SUBMITTED
    assert review.review_snapshot == original
