"""Unit tests for the 004 human-review application service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from legal_ai.application.review_service import ReviewService
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import (
    CommentSeverity,
    CommentStatus,
    DraftStatus,
    ReviewOperationStatus,
    ReviewStatus,
)
from legal_ai.domain.errors import (
    AnchorVersionMismatchError,
    IdempotencyConflictError,
    InvalidReviewTransitionError,
    OpenBlockingCommentsError,
    ReviewOperationInProgressError,
)
from legal_ai.domain.review import DocumentReview, ReviewOperationRequest
from legal_ai.domain.review_comment import ReviewComment


class _Operations:
    def __init__(self) -> None:
        self.items: dict[tuple[str, uuid.UUID, str], ReviewOperationRequest] = {}

    async def get(self, operation, resource_id, key):
        return self.items.get((operation, resource_id, key))

    async def create(self, request):
        self.items[
            (request.operation, request.resource_id, request.idempotency_key)
        ] = request
        return request

    async def update(self, request):
        self.items[
            (request.operation, request.resource_id, request.idempotency_key)
        ] = request
        return request

    async def delete_expired(self, operation, resource_id, key):
        self.items.pop((operation, resource_id, key), None)


class _Reviews:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, DocumentReview] = {}

    async def get_by_id(self, review_id):
        return self.items.get(review_id)

    async def get_current(self, draft_id, draft_version):
        return next(
            (
                review
                for review in self.items.values()
                if review.draft_id == draft_id and review.draft_version == draft_version
            ),
            None,
        )

    async def create(self, review):
        self.items[review.id] = review
        return review

    async def update(self, review, expected_version):
        current = self.items.get(review.id)
        if current is None or current.version != expected_version:
            return None
        review.version = expected_version + 1
        self.items[review.id] = review
        return review


class _Comments:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, ReviewComment] = {}

    async def get_by_id(self, comment_id):
        return self.items.get(comment_id)

    async def create(self, comment):
        self.items[comment.id] = comment
        return comment

    async def update(self, comment, expected_version):
        current = self.items.get(comment.id)
        if current is None or current.version != expected_version:
            return None
        comment.version = expected_version + 1
        self.items[comment.id] = comment
        return comment

    async def count_open_blocking(self, review_id):
        return sum(
            comment.review_id == review_id and comment.is_open_blocking()
            for comment in self.items.values()
        )


class _Events:
    def __init__(self) -> None:
        self.items = []

    async def create(self, event):
        self.items.append(event)
        return event

    async def list_by_review(self, review_id, offset, limit):
        events = [event for event in self.items if event.review_id == review_id]
        return events[offset : offset + limit], len(events)


def _uow(draft: Draft):
    async def update_status(draft_id, new_status, version):
        if draft_id != draft.id or draft.version != version:
            return None
        draft.status = new_status
        draft.version += 1
        return draft

    return SimpleNamespace(
        drafts=SimpleNamespace(
            get_by_id=lambda draft_id: _async_value(draft),
            update_status=update_status,
        ),
        reviews=_Reviews(),
        review_operations=_Operations(),
        review_comments=_Comments(),
        review_events=_Events(),
    )


async def _async_value(value):
    return value


def _draft() -> Draft:
    now = datetime.now(UTC)
    return Draft(
        id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        case_file_id=uuid.uuid4(),
        title="Review test",
        content="Approved content",
        status=DraftStatus.APROBADO,
        version=1,
        generation_number=1,
        context_snapshot={"locale": "es-AR"},
        context_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.unit
async def test_review_lifecycle_creates_snapshot_comments_and_events() -> None:
    draft = _draft()
    uow = _uow(draft)
    service = ReviewService(uow)
    key = "review-key-000001"

    created = await service.create_review(draft.id, 1, 1, " Ana ", key, "req-1")
    review = created.value
    assert created.status_code == 201
    assert review.review_snapshot["draft_version"] == 1
    assert review.review_snapshot_sha256

    comment = ReviewComment(
        id=uuid.uuid4(),
        review_id=review.id,
        draft_version=1,
        author="Reviewer",
        severity=CommentSeverity.INFO,
        status=CommentStatus.OPEN,
        body="Please verify the wording",
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    added = await service.add_comment(
        review.id,
        comment,
        "comment-key-0001",
        "req-2",
        {"draft_version": 1, "body": comment.body},
    )
    assert added.status_code == 201
    submitted = await service.submit(
        review.id, 1, "Submitter", "submit-key-0001", "req-3", {"expected_version": 1}
    )
    assert submitted.value.status == ReviewStatus.SUBMITTED
    approved = await service.approve(
        review.id,
        2,
        "Approver",
        True,
        "approve-key-0001",
        "req-4",
        {"expected_version": 2, "human_review_confirmed": True},
    )
    assert approved.value.status == ReviewStatus.CLOSED
    assert len(uow.review_events.items) == 4


@pytest.mark.unit
async def test_review_mutation_rejects_blocking_comment_and_anchor_mismatch() -> None:
    draft = _draft()
    uow = _uow(draft)
    service = ReviewService(uow)
    created = await service.create_review(
        draft.id, 1, 1, "Reviewer", "review-key-000002", "req-1"
    )
    review = created.value
    blocking = ReviewComment(
        id=uuid.uuid4(),
        review_id=review.id,
        draft_version=1,
        author="Reviewer",
        severity=CommentSeverity.BLOCKING,
        status=CommentStatus.OPEN,
        body="Blocking issue",
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await service.add_comment(
        review.id,
        blocking,
        "comment-key-0002",
        "req-2",
        {"draft_version": 1, "body": blocking.body},
    )
    with pytest.raises(OpenBlockingCommentsError):
        await service.submit(
            review.id,
            1,
            "Submitter",
            "submit-key-0002",
            "req-3",
            {"expected_version": 1},
        )

    mismatched = ReviewComment(
        id=uuid.uuid4(),
        review_id=review.id,
        draft_version=1,
        author="Reviewer",
        severity=CommentSeverity.INFO,
        status=CommentStatus.OPEN,
        body="Wrong anchor",
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        anchor={"draft_version": 99},
    )
    with pytest.raises(AnchorVersionMismatchError):
        await service.add_comment(
            review.id,
            mismatched,
            "comment-key-0003",
            "req-4",
            {"draft_version": 99, "body": mismatched.body},
        )


@pytest.mark.unit
async def test_review_idempotency_replay_conflict_active_and_expiry() -> None:
    draft = _draft()
    uow = _uow(draft)
    service = ReviewService(uow)
    payload = {"draft_version": 1, "expected_version": 1, "opened_by": "Reviewer"}
    first = await service.create_review(
        draft.id, 1, 1, "Reviewer", "review-key-000003", "req-1"
    )
    replay = await service.create_review(
        draft.id, 1, 1, "Reviewer", "review-key-000003", "req-2"
    )
    assert str(first.value.id) == replay.value["id"]
    assert replay.status_code == 201

    with pytest.raises(IdempotencyConflictError):
        await service.create_review(
            draft.id, 2, 2, "Reviewer", "review-key-000003", "req-3"
        )

    active = ReviewOperationRequest(
        id=uuid.uuid4(),
        operation="CREATE_REVIEW",
        resource_id=uuid.uuid4(),
        idempotency_key="review-key-000004",
        request_hash=service.request_hash(payload),
        status=ReviewOperationStatus.PROCESSING,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        request_id="req-active",
        created_at=datetime.now(UTC),
    )
    uow.review_operations.items[
        (active.operation, active.resource_id, active.idempotency_key)
    ] = active
    with pytest.raises(ReviewOperationInProgressError):
        await service._claim(
            active.operation,
            active.resource_id,
            active.idempotency_key,
            payload,
            "req-active-2",
        )

    active.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert (
        await service._claim(
            active.operation,
            active.resource_id,
            active.idempotency_key,
            payload,
            "req-expired",
        )
        is None
    )


@pytest.mark.unit
async def test_review_mutations_are_blocked_after_draft_finalization() -> None:
    draft = _draft()
    draft.finalized_at = datetime.now(UTC)
    draft.finalized_by = "Editor"
    uow = _uow(draft)
    service = ReviewService(uow)
    review = DocumentReview(
        id=uuid.uuid4(),
        draft_id=draft.id,
        draft_version=draft.version,
        review_snapshot={"content": "approved"},
        review_snapshot_sha256="a" * 64,
        status=ReviewStatus.OPEN,
        opened_by="Reviewer",
        version=1,
        opened_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    uow.reviews.items[review.id] = review
    comment = ReviewComment(
        id=uuid.uuid4(),
        review_id=review.id,
        draft_version=draft.version,
        author="Reviewer",
        severity=CommentSeverity.INFO,
        status=CommentStatus.OPEN,
        body="blocked",
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(InvalidReviewTransitionError):
        await service.add_comment(
            review.id,
            comment,
            "comment-key-0005",
            "req-finalized",
            {"draft_version": draft.version, "body": comment.body},
        )
