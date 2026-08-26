"""Write-once finalization service for approved drafts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.exc import IntegrityError

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
    OfficialDocumentNumberConflictError,
    OpenBlockingCommentsError,
)
from legal_ai.domain.official_document import OfficialDocumentIdentifier
from legal_ai.domain.review import DocumentReview
from legal_ai.domain.review_event import ReviewEvent
from legal_ai.observability.logging import log_event
from legal_ai.schemas.document import LegalDocument
from legal_ai.schemas.validation import validate_actor


@dataclass(frozen=True)
class FinalizationResult:
    """Finalization response and status used by the HTTP adapter."""

    draft: Draft
    snapshot: dict[str, object]
    sha256: str
    status_code: int
    identifier: OfficialDocumentIdentifier | None = None


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
        official_number: int | None = None,
        issued_on: date | None = None,
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
            identifier = (
                await self._uow.official_document_identifiers.get_by_draft(draft.id)
                if official_number is not None and issued_on is not None
                else None
            )
            return self._replay_or_conflict(
                draft,
                review,
                expected_version,
                actor,
                notes,
                official_number,
                issued_on,
                identifier,
            )

        if draft.status != DraftStatus.APROBADO:
            raise DraftNotApprovedError(details={"draft_id": str(draft_id)})
        if draft.version != expected_version:
            raise ConcurrentModification004Error(details={"draft_id": str(draft_id)})
        if await self._uow.review_comments.count_open_blocking(review.id):
            raise OpenBlockingCommentsError()

        self._validate_structured_snapshot(review)
        identifier = None
        if official_number is not None or issued_on is not None:
            if official_number is None or issued_on is None:
                raise InvalidFinalizationError(details={"field": "official_number"})
            template = await self._uow.templates.get_by_id(draft.template_id)
            if template is None:
                raise InvalidFinalizationError(details={"field": "template"})
            document_type = str(template.document_type)
            existing_identifier = (
                await self._uow.official_document_identifiers.get_by_identity(
                    document_type, official_number, issued_on.year
                )
            )
            if (
                existing_identifier is not None
                and existing_identifier.draft_id != draft.id
            ):
                raise OfficialDocumentNumberConflictError()
            identifier = OfficialDocumentIdentifier(
                id=uuid.uuid4(),
                draft_id=draft.id,
                document_type=document_type,
                number=official_number,
                year=issued_on.year,
                issued_on=issued_on,
                created_at=datetime.now(UTC),
            )
            try:
                if existing_identifier is None:
                    identifier = await self._uow.official_document_identifiers.create(
                        identifier
                    )
                else:
                    identifier = existing_identifier
            except IntegrityError as exc:
                raise OfficialDocumentNumberConflictError() from exc

        serialized = self._snapshot(draft, review, official_number, issued_on)
        finalized_at = datetime.now(UTC)
        if official_number is None and issued_on is None:
            updated = await self._uow.drafts.update_finalization(
                draft_id,
                expected_version,
                actor,
                finalized_at,
                notes,
                serialized.snapshot,
                serialized.sha256,
            )
        else:
            updated = await self._uow.drafts.update_finalization(
                draft_id,
                expected_version,
                actor,
                finalized_at,
                notes,
                serialized.snapshot,
                serialized.sha256,
                official_number,
                issued_on,
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
        return FinalizationResult(
            updated, serialized.snapshot, serialized.sha256, 200, identifier
        )

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
        draft: Draft,
        review: DocumentReview,
        official_number: int | None = None,
        issued_on: date | None = None,
    ) -> SerializedCanonicalDocument:
        canonical = CanonicalDocumentBuilder.build(draft, review)
        if official_number is not None and issued_on is not None:
            canonical.document["official_number"] = official_number
            canonical.document["issued_on"] = issued_on.isoformat()
        return CanonicalDocumentBuilder.serialize(canonical)

    @staticmethod
    def _validate_structured_snapshot(review: DocumentReview) -> None:
        payload = review.review_snapshot.get("document")
        if not isinstance(payload, dict):
            return
        try:
            document = LegalDocument.model_validate(payload)
            document.validate_for_approval()
        except Exception as exc:
            raise InvalidFinalizationError(
                details={"field": "review_snapshot.document"}
            ) from exc

    @staticmethod
    def _replay_or_conflict(
        draft: Draft,
        review: DocumentReview,
        expected_version: int,
        actor: str,
        notes: str | None,
        official_number: int | None,
        issued_on: date | None,
        identifier: OfficialDocumentIdentifier | None,
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
        if official_number is not None or issued_on is not None:
            if identifier is None or (
                official_number != identifier.number
                or issued_on != identifier.issued_on
            ):
                raise DraftAlreadyFinalizedError(details={"draft_id": str(draft.id)})
        elif identifier is not None:
            raise DraftAlreadyFinalizedError(details={"draft_id": str(draft.id)})
        expected = FinalizationService._snapshot(
            draft, review, official_number, issued_on
        )
        if (
            expected.snapshot != draft.final_snapshot
            or expected.sha256 != draft.final_snapshot_sha256
        ):
            raise DraftAlreadyFinalizedError(details={"draft_id": str(draft.id)})
        return FinalizationResult(
            draft, draft.final_snapshot, draft.final_snapshot_sha256, 200, identifier
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
