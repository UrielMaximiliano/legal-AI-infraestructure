"""Application service for human review lifecycle and audit events."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import (
    CommentStatus,
    DraftStatus,
    ReviewOperationStatus,
    ReviewStatus,
)
from legal_ai.domain.errors import (
    AnchorVersionMismatchError,
    CommentNotFoundError,
    ConcurrentModification004Error,
    DraftNotFound004Error,
    HumanReviewRequiredError,
    IdempotencyConflictError,
    InvalidReviewTransitionError,
    MissingReviewReasonError,
    OpenBlockingCommentsError,
    ReviewNotFoundError,
    ReviewOperationInProgressError,
    ReviewVersionMismatchError,
)
from legal_ai.domain.review import DocumentReview, ReviewOperationRequest
from legal_ai.domain.review_comment import ReviewComment
from legal_ai.domain.review_event import ReviewEvent
from legal_ai.observability.logging import log_event
from legal_ai.schemas.validation import validate_actor

T = TypeVar("T")


@dataclass
class ReviewOperationResult:
    """Service result carrying the response status for replay semantics."""

    value: Any
    status_code: int


class ReviewService:
    """Coordinate review state, comments, optimistic locking and audit."""

    IDEMPOTENCY_WINDOW = timedelta(hours=24)

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    @staticmethod
    def request_hash(payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    async def _claim(
        self,
        operation: str,
        resource_id: uuid.UUID,
        idempotency_key: str,
        payload: dict[str, Any],
        request_id: str,
    ) -> ReviewOperationResult | None:
        request_hash = self.request_hash(payload)
        existing = await self._uow.review_operations.get(
            operation, resource_id, idempotency_key
        )
        now = datetime.now(UTC)
        if existing and existing.expires_at <= now:
            await self._uow.review_operations.delete_expired(
                operation, resource_id, idempotency_key
            )
            existing = None
        if existing:
            if existing.request_hash != request_hash:
                raise IdempotencyConflictError(details={"operation": operation})
            if existing.status == ReviewOperationStatus.PROCESSING:
                raise ReviewOperationInProgressError()
            if existing.status == ReviewOperationStatus.SUCCEEDED:
                return ReviewOperationResult(
                    existing.response_payload or {}, existing.response_status or 200
                )

        claim = ReviewOperationRequest(
            id=uuid.uuid4(),
            operation=operation,
            resource_id=resource_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status=ReviewOperationStatus.PROCESSING,
            expires_at=now + self.IDEMPOTENCY_WINDOW,
            request_id=request_id,
            created_at=now,
        )
        await self._uow.review_operations.create(claim)
        return None

    async def _complete(
        self,
        operation: str,
        resource_id: uuid.UUID,
        idempotency_key: str,
        payload: dict[str, Any],
        value: T,
        status_code: int,
    ) -> ReviewOperationResult:
        claim = await self._uow.review_operations.get(
            operation, resource_id, idempotency_key
        )
        if claim is not None:
            claim.status = ReviewOperationStatus.SUCCEEDED
            claim.response_status = status_code
            claim.response_payload = payload
            claim.completed_at = datetime.now(UTC)
            await self._uow.review_operations.update(claim)
        return ReviewOperationResult(value, status_code)

    async def _draft(self, draft_id: uuid.UUID) -> Draft:
        draft = await self._uow.drafts.get_by_id(draft_id)
        if draft is None:
            raise DraftNotFound004Error(details={"draft_id": str(draft_id)})
        return draft

    async def _event(
        self,
        review: DocumentReview,
        event_type: str,
        actor: str,
        request_id: str,
        summary: dict[str, Any] | None = None,
    ) -> None:
        await self._uow.review_events.create(
            ReviewEvent(
                id=uuid.uuid4(),
                review_id=review.id,
                draft_id=review.draft_id,
                resource_type="REVIEW",
                resource_id=str(review.id),
                event_type=event_type,
                actor=actor,
                request_id=request_id,
                draft_version=review.draft_version,
                summary=summary or {},
                created_at=datetime.now(UTC),
            )
        )
        log_event(
            "review_state_transition",
            request_id=request_id,
            draft_id=review.draft_id,
            review_id=review.id,
            operation=event_type,
            phase="state_transition",
            result="success",
        )

    async def current(self, draft_id: uuid.UUID) -> DocumentReview:
        draft = await self._draft(draft_id)
        review = await self._uow.reviews.get_current(draft.id, draft.version)
        if review is None:
            raise ReviewNotFoundError(details={"draft_id": str(draft_id)})
        return review

    async def create_review(
        self,
        draft_id: uuid.UUID,
        draft_version: int,
        expected_version: int,
        opened_by: str,
        idempotency_key: str,
        request_id: str,
    ) -> ReviewOperationResult:
        payload = {
            "draft_version": draft_version,
            "expected_version": expected_version,
            "opened_by": opened_by,
        }
        replay = await self._claim(
            "CREATE_REVIEW", draft_id, idempotency_key, payload, request_id
        )
        if replay is not None:
            return replay
        draft = await self._draft(draft_id)
        if draft.version != expected_version or draft.version != draft_version:
            raise ConcurrentModification004Error(details={"draft_id": str(draft_id)})
        if draft.is_finalized():
            raise InvalidReviewTransitionError()
        existing = await self._uow.reviews.get_current(draft_id, draft_version)
        if existing is not None:
            return await self._complete(
                "CREATE_REVIEW",
                draft_id,
                idempotency_key,
                self._review_payload(existing),
                existing,
                200,
            )
        snapshot = {
            "draft_id": str(draft.id),
            "draft_version": draft.version,
            "title": draft.title,
            "content": draft.content or "",
            "context_snapshot": draft.context_snapshot,
        }
        digest = self.request_hash(snapshot)
        now = datetime.now(UTC)
        review = await self._uow.reviews.create(
            DocumentReview(
                id=uuid.uuid4(),
                draft_id=draft_id,
                draft_version=draft_version,
                review_snapshot=snapshot,
                review_snapshot_sha256=digest,
                status=ReviewStatus.OPEN,
                opened_by=validate_actor(opened_by) or "",
                version=1,
                opened_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await self._event(review, "REVIEW_OPENED", opened_by, request_id)
        return await self._complete(
            "CREATE_REVIEW",
            draft_id,
            idempotency_key,
            self._review_payload(review),
            review,
            201,
        )

    async def add_comment(
        self,
        review_id: uuid.UUID,
        comment: ReviewComment,
        idempotency_key: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> ReviewOperationResult:
        replay = await self._claim(
            "CREATE_COMMENT", review_id, idempotency_key, payload, request_id
        )
        if replay is not None:
            return replay
        review = await self._review(review_id)
        await self._ensure_review_mutable(review)
        if comment.draft_version != review.draft_version:
            raise AnchorVersionMismatchError()
        if comment.anchor and comment.anchor.get("draft_version") not in (
            None,
            review.draft_version,
        ):
            raise AnchorVersionMismatchError()
        if comment.parent_comment_id is not None:
            parent = await self._uow.review_comments.get_by_id(
                comment.parent_comment_id
            )
            if parent is None or parent.review_id != review_id:
                raise CommentNotFoundError()
        created = await self._uow.review_comments.create(comment)
        await self._event(review, "COMMENT_ADDED", comment.author, request_id)
        return await self._complete(
            "CREATE_COMMENT",
            review_id,
            idempotency_key,
            self._comment_payload(created),
            created,
            201,
        )

    async def update_comment(
        self,
        review_id: uuid.UUID,
        comment_id: uuid.UUID,
        expected_version: int,
        status: CommentStatus,
        resolved_by: str | None,
        idempotency_key: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> ReviewOperationResult:
        replay = await self._claim(
            "UPDATE_COMMENT", review_id, idempotency_key, payload, request_id
        )
        if replay is not None:
            return replay
        review = await self._review(review_id)
        await self._ensure_review_mutable(review)
        comment = await self._uow.review_comments.get_by_id(comment_id)
        if comment is None or comment.review_id != review_id:
            raise CommentNotFoundError()
        if comment.version != expected_version:
            raise ReviewVersionMismatchError()
        if status == CommentStatus.OPEN:
            resolved_by = None
            resolved_at = None
        else:
            resolved_at = datetime.now(UTC)
        comment.status = status
        comment.resolved_by = resolved_by
        comment.resolved_at = resolved_at
        updated = await self._uow.review_comments.update(comment, expected_version)
        if updated is None:
            raise ConcurrentModification004Error(
                details={"comment_id": str(comment_id)}
            )
        await self._event(
            review, "COMMENT_STATUS_CHANGED", resolved_by or "", request_id
        )
        return await self._complete(
            "UPDATE_COMMENT",
            review_id,
            idempotency_key,
            self._comment_payload(updated),
            updated,
            200,
        )

    async def submit(
        self,
        review_id: uuid.UUID,
        expected_version: int,
        submitted_by: str,
        idempotency_key: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> ReviewOperationResult:
        return await self._decide(
            "SUBMIT_REVIEW",
            review_id,
            expected_version,
            ReviewStatus.SUBMITTED,
            submitted_by,
            None,
            idempotency_key,
            request_id,
            payload,
        )

    async def approve(
        self,
        review_id: uuid.UUID,
        expected_version: int,
        decided_by: str,
        human_review_confirmed: bool,
        idempotency_key: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> ReviewOperationResult:
        if not human_review_confirmed:
            raise HumanReviewRequiredError()
        return await self._decide(
            "APPROVE_REVIEW",
            review_id,
            expected_version,
            ReviewStatus.CLOSED,
            decided_by,
            DraftStatus.APROBADO,
            idempotency_key,
            request_id,
            payload,
        )

    async def request_changes(
        self,
        review_id: uuid.UUID,
        expected_version: int,
        decided_by: str,
        reason: str,
        idempotency_key: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> ReviewOperationResult:
        if not reason.strip():
            raise MissingReviewReasonError()
        return await self._decide(
            "REQUEST_CHANGES",
            review_id,
            expected_version,
            ReviewStatus.CHANGES_REQUESTED,
            decided_by,
            DraftStatus.RECHAZADO,
            idempotency_key,
            request_id,
            payload,
        )

    async def _decide(
        self,
        operation: str,
        review_id: uuid.UUID,
        expected_version: int,
        target_status: ReviewStatus,
        actor: str,
        draft_status: DraftStatus | None,
        idempotency_key: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> ReviewOperationResult:
        replay = await self._claim(
            operation, review_id, idempotency_key, payload, request_id
        )
        if replay is not None:
            return replay
        review = await self._review(review_id)
        await self._ensure_review_mutable(review)
        if await self._uow.review_comments.count_open_blocking(review_id):
            raise OpenBlockingCommentsError()
        if target_status == ReviewStatus.SUBMITTED:
            if review.status != ReviewStatus.OPEN:
                raise InvalidReviewTransitionError()
        elif review.status != ReviewStatus.SUBMITTED:
            raise InvalidReviewTransitionError()
        if review.version != expected_version:
            raise ReviewVersionMismatchError()
        now = datetime.now(UTC)
        review.status = target_status
        if target_status == ReviewStatus.SUBMITTED:
            review.submitted_by = actor
            review.submitted_at = now
        else:
            review.decided_by = actor
            review.decided_at = now
            review.closed_at = now
        updated = await self._uow.reviews.update(review, expected_version)
        if updated is None:
            raise ConcurrentModification004Error(details={"review_id": str(review_id)})
        if draft_status is not None:
            draft = await self._draft(review.draft_id)
            changed = await self._uow.drafts.update_status(
                draft.id, draft_status, draft.version
            )
            if changed is None:
                raise ConcurrentModification004Error(
                    details={"draft_id": str(draft.id)}
                )
        await self._event(updated, target_status.value, actor, request_id)
        return await self._complete(
            operation,
            review_id,
            idempotency_key,
            self._review_payload(updated),
            updated,
            200,
        )

    async def history(
        self, review_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[ReviewEvent], int]:
        await self._review(review_id)
        return await self._uow.review_events.list_by_review(review_id, offset, limit)

    async def _review(self, review_id: uuid.UUID) -> DocumentReview:
        review = await self._uow.reviews.get_by_id(review_id)
        if review is None:
            raise ReviewNotFoundError(details={"review_id": str(review_id)})
        return review

    async def _ensure_review_mutable(self, review: DocumentReview) -> None:
        draft = await self._draft(review.draft_id)
        if draft.is_finalized() or review.is_closed():
            raise InvalidReviewTransitionError()

    @staticmethod
    def _review_payload(review: DocumentReview) -> dict[str, Any]:
        return {
            "id": str(review.id),
            "draft_id": str(review.draft_id),
            "draft_version": review.draft_version,
            "review_snapshot_sha256": review.review_snapshot_sha256,
            "status": review.status.value,
            "version": review.version,
            "opened_by": review.opened_by,
            "submitted_by": review.submitted_by,
            "decided_by": review.decided_by,
            "opened_at": review.opened_at.isoformat(),
            "submitted_at": review.submitted_at.isoformat()
            if review.submitted_at
            else None,
            "decided_at": review.decided_at.isoformat() if review.decided_at else None,
            "closed_at": review.closed_at.isoformat() if review.closed_at else None,
            "created_at": review.created_at.isoformat(),
            "updated_at": review.updated_at.isoformat(),
        }

    @staticmethod
    def _comment_payload(comment: ReviewComment) -> dict[str, Any]:
        return {
            "id": str(comment.id),
            "review_id": str(comment.review_id),
            "parent_comment_id": str(comment.parent_comment_id)
            if comment.parent_comment_id
            else None,
            "draft_version": comment.draft_version,
            "author": comment.author,
            "severity": comment.severity.value,
            "status": comment.status.value,
            "body": comment.body,
            "anchor": comment.anchor,
            "version": comment.version,
            "created_at": comment.created_at.isoformat(),
            "updated_at": comment.updated_at.isoformat(),
            "resolved_by": comment.resolved_by,
            "resolved_at": comment.resolved_at.isoformat()
            if comment.resolved_at
            else None,
        }
