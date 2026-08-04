"""SQLAlchemy repository for reviews and scoped review idempotency."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import (
    DocumentReviewModel,
    ReviewOperationRequestModel,
)
from legal_ai.domain.enums import ReviewStatus
from legal_ai.domain.review import DocumentReview, ReviewOperationRequest


class SQLAlchemyReviewRepository:
    """Review persistence with immutable snapshot mapping."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, review_id: UUID) -> DocumentReview | None:
        result = await self._session.execute(
            select(DocumentReviewModel).where(DocumentReviewModel.id == review_id)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_current(
        self, draft_id: UUID, draft_version: int
    ) -> DocumentReview | None:
        result = await self._session.execute(
            select(DocumentReviewModel).where(
                DocumentReviewModel.draft_id == draft_id,
                DocumentReviewModel.draft_version == draft_version,
            )
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_latest_for_draft(self, draft_id: UUID) -> DocumentReview | None:
        result = await self._session.execute(
            select(DocumentReviewModel)
            .where(DocumentReviewModel.draft_id == draft_id)
            .order_by(
                DocumentReviewModel.draft_version.desc(),
                DocumentReviewModel.created_at.desc(),
                DocumentReviewModel.id.desc(),
            )
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def create(self, review: DocumentReview) -> DocumentReview:
        model = DocumentReviewModel(
            id=review.id,
            draft_id=review.draft_id,
            draft_version=review.draft_version,
            review_snapshot=review.review_snapshot,
            review_snapshot_sha256=review.review_snapshot_sha256,
            status=review.status,
            version=review.version,
            opened_by=review.opened_by,
            submitted_by=review.submitted_by,
            decided_by=review.decided_by,
            opened_at=review.opened_at,
            submitted_at=review.submitted_at,
            decided_at=review.decided_at,
            closed_at=review.closed_at,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def update(
        self, review: DocumentReview, expected_version: int
    ) -> DocumentReview | None:
        values = {
            "status": review.status,
            "version": expected_version + 1,
            "submitted_by": review.submitted_by,
            "decided_by": review.decided_by,
            "submitted_at": review.submitted_at,
            "decided_at": review.decided_at,
            "closed_at": review.closed_at,
            "updated_at": datetime.now(UTC),
        }
        result = await self._session.execute(
            update(DocumentReviewModel)
            .where(
                DocumentReviewModel.id == review.id,
                DocumentReviewModel.version == expected_version,
            )
            .values(**values)
            .returning(DocumentReviewModel)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def list_by_draft(
        self, draft_id: UUID, draft_version: int, offset: int, limit: int
    ) -> tuple[list[DocumentReview], int]:
        filters = [
            DocumentReviewModel.draft_id == draft_id,
            DocumentReviewModel.draft_version == draft_version,
        ]
        total = await self._session.scalar(
            select(func.count()).select_from(DocumentReviewModel).where(*filters)
        )
        result = await self._session.execute(
            select(DocumentReviewModel)
            .where(*filters)
            .order_by(
                DocumentReviewModel.created_at.desc(), DocumentReviewModel.id.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return [self._to_domain(model) for model in result.scalars().all()], int(
            total or 0
        )

    @staticmethod
    def _to_domain(model: DocumentReviewModel) -> DocumentReview:
        return DocumentReview(
            id=model.id,
            draft_id=model.draft_id,
            draft_version=model.draft_version,
            review_snapshot=model.review_snapshot,
            review_snapshot_sha256=model.review_snapshot_sha256,
            status=ReviewStatus(model.status),
            opened_by=model.opened_by,
            version=model.version,
            opened_at=model.opened_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
            submitted_by=model.submitted_by,
            decided_by=model.decided_by,
            submitted_at=model.submitted_at,
            decided_at=model.decided_at,
            closed_at=model.closed_at,
        )


class SQLAlchemyReviewOperationRequestRepository:
    """Scoped idempotency repository for review mutations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, operation: str, resource_id: UUID, idempotency_key: str
    ) -> ReviewOperationRequest | None:
        result = await self._session.execute(
            select(ReviewOperationRequestModel).where(
                ReviewOperationRequestModel.operation == operation,
                ReviewOperationRequestModel.resource_id == resource_id,
                ReviewOperationRequestModel.idempotency_key == idempotency_key,
            )
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def create(self, request: ReviewOperationRequest) -> ReviewOperationRequest:
        model = ReviewOperationRequestModel(
            id=request.id,
            operation=request.operation,
            resource_id=request.resource_id,
            idempotency_key=request.idempotency_key,
            request_hash=request.request_hash,
            status=request.status,
            response_status=request.response_status,
            response_payload=request.response_payload,
            error_code=request.error_code,
            created_at=request.created_at,
            completed_at=request.completed_at,
            expires_at=request.expires_at,
            request_id=request.request_id,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def update(self, request: ReviewOperationRequest) -> ReviewOperationRequest:
        result = await self._session.execute(
            update(ReviewOperationRequestModel)
            .where(ReviewOperationRequestModel.id == request.id)
            .values(
                status=request.status,
                response_status=request.response_status,
                response_payload=request.response_payload,
                error_code=request.error_code,
                completed_at=request.completed_at,
            )
            .returning(ReviewOperationRequestModel)
        )
        model = result.scalars().one()
        return self._to_domain(model)

    async def delete_expired(
        self, operation: str, resource_id: UUID, idempotency_key: str
    ) -> None:
        await self._session.execute(
            delete(ReviewOperationRequestModel).where(
                ReviewOperationRequestModel.operation == operation,
                ReviewOperationRequestModel.resource_id == resource_id,
                ReviewOperationRequestModel.idempotency_key == idempotency_key,
            )
        )

    @staticmethod
    def _to_domain(model: ReviewOperationRequestModel) -> ReviewOperationRequest:
        return ReviewOperationRequest(
            id=model.id,
            operation=model.operation,
            resource_id=model.resource_id,
            idempotency_key=model.idempotency_key,
            request_hash=model.request_hash,
            status=model.status,
            expires_at=model.expires_at,
            request_id=model.request_id,
            created_at=model.created_at,
            response_status=model.response_status,
            response_payload=model.response_payload,
            error_code=model.error_code,
            completed_at=model.completed_at,
        )
