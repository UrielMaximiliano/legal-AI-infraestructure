"""Write-once finalization service for approved drafts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.canonical_document import (
    CanonicalDocumentBuilder,
    SerializedCanonicalDocument,
)
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus, ReviewStatus
from legal_ai.domain.errors import (
    ConcurrentModification004Error,
    DraftAlreadyFinalizedError,
    DraftNotApprovedError,
    DraftNotFound004Error,
    InvalidFinalizationError,
    OpenBlockingCommentsError,
)
from legal_ai.domain.review import DocumentReview
from legal_ai.domain.review_event import ReviewEvent
from legal_ai.observability.logging import log_event
from legal_ai.schemas.validation import validate_actor


@dataclass(frozen=True)
class FinalizationResult:
    """Finalization response and status used by the HTTP adapter."""

    draft: Draft
    snapshot: dict[str, object]
    sha256: str
    status_code: int


class FinalizationService:
    """Finalize an approved draft exactly once inside one short DB transaction."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def finalize(
        self,
        draft_id: uuid.UUID,
        expected_version: int,
        finalized_by: str,
        finalization_notes: str | None,
        request_id: str,
    ) -> FinalizationResult:
        actor = self._actor(finalized_by)
        notes = self._notes(finalization_notes)
        draft = await self._uow.drafts.get_by_id_for_update(draft_id)
        if draft is None:
            raise DraftNotFound004Error(details={"draft_id": str(draft_id)})

        review = await self._uow.reviews.get_latest_for_draft(draft_id)
        if review is None or review.status != ReviewStatus.CLOSED:
            raise InvalidFinalizationError(details={"field": "review"})

        if draft.is_finalized():
            return self._replay_or_conflict(
                draft, review, expected_version, actor, notes
            )

        if draft.status != DraftStatus.APROBADO:
            raise DraftNotApprovedError(details={"draft_id": str(draft_id)})
        if draft.version != expected_version:
            raise ConcurrentModification004Error(details={"draft_id": str(draft_id)})
        if await self._uow.review_comments.count_open_blocking(review.id):
            raise OpenBlockingCommentsError()

        serialized = self._snapshot(draft, review)
        finalized_at = datetime.now(UTC)
        updated = await self._uow.drafts.update_finalization(
            draft_id,
            expected_version,
            actor,
            finalized_at,
            notes,
            serialized.snapshot,
            serialized.sha256,
        )
        if updated is None:
            raise ConcurrentModification004Error(details={"draft_id": str(draft_id)})
        await self._uow.review_events.create(
            self._event(
                updated, review.id, actor, request_id, serialized.sha256, finalized_at
            )
        )
        log_event(
            "draft_finalization_completed",
            request_id=request_id,
            draft_id=updated.id,
            review_id=review.id,
            draft_version=updated.version,
            sha256=serialized.sha256,
            result="success",
        )
        return FinalizationResult(updated, serialized.snapshot, serialized.sha256, 200)

    @staticmethod
    def _actor(value: str) -> str:
        try:
            actor = validate_actor(value)
        except ValueError as exc:
            raise InvalidFinalizationError(details={"field": "finalized_by"}) from exc
        if actor is None:
            raise InvalidFinalizationError(details={"field": "finalized_by"})
        return actor

    @staticmethod
    def _notes(value: str | None) -> str | None:
        if value is None:
            return None
        notes = value.strip()
        if len(notes) > 2000:
            raise InvalidFinalizationError(details={"field": "finalization_notes"})
        return notes or None

    @staticmethod
    def _snapshot(
        draft: Draft, review: DocumentReview
    ) -> SerializedCanonicalDocument:
        return CanonicalDocumentBuilder.serialize(
            CanonicalDocumentBuilder.build(draft, review)
        )

    @staticmethod
    def _replay_or_conflict(
        draft: Draft,
        review: DocumentReview,
        expected_version: int,
        actor: str,
        notes: str | None,
    ) -> FinalizationResult:
        if expected_version != draft.version - 1:
            raise ConcurrentModification004Error(details={"draft_id": str(draft.id)})
        if (
            actor != draft.finalized_by
            or notes != draft.finalization_notes
            or draft.final_snapshot is None
            or draft.final_snapshot_sha256 is None
        ):
            raise DraftAlreadyFinalizedError(details={"draft_id": str(draft.id)})
        expected = FinalizationService._snapshot(draft, review)
        if (
            expected.snapshot != draft.final_snapshot
            or expected.sha256 != draft.final_snapshot_sha256
        ):
            raise DraftAlreadyFinalizedError(details={"draft_id": str(draft.id)})
        return FinalizationResult(
            draft, draft.final_snapshot, draft.final_snapshot_sha256, 200
        )

    @staticmethod
    def _event(
        draft: Draft,
        review_id: uuid.UUID,
        actor: str,
        request_id: str,
        snapshot_sha256: str,
        created_at: datetime,
    ) -> ReviewEvent:
        return ReviewEvent(
            id=uuid.uuid4(),
            review_id=review_id,
            draft_id=draft.id,
            resource_type="DRAFT",
            resource_id=str(draft.id),
            event_type="DRAFT_FINALIZED",
            actor=actor,
            request_id=request_id,
            draft_version=draft.version,
            summary={"final_snapshot_sha256": snapshot_sha256},
            created_at=created_at,
        )
