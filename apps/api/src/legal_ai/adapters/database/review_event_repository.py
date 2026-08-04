"""SQLAlchemy append-only review-event repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import ReviewEventModel
from legal_ai.domain.review_event import ReviewEvent
from legal_ai.observability.logging import log_event


class SQLAlchemyReviewEventRepository:
    """Write-once audit event storage."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, event: ReviewEvent) -> ReviewEvent:
        model = ReviewEventModel(
            id=event.id,
            review_id=event.review_id,
            draft_id=event.draft_id,
            export_id=event.export_id,
            attempt_id=event.attempt_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            event_type=event.event_type,
            actor=event.actor,
            request_id=event.request_id,
            run_id=event.run_id,
            draft_version=event.draft_version,
            summary=event.summary or {},
            created_at=event.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        log_event(
            "review_event_persisted",
            request_id=event.request_id,
            draft_id=event.draft_id,
            review_id=event.review_id,
            export_id=event.export_id,
            attempt_id=event.attempt_id,
            run_id=event.run_id,
            resource_type=event.resource_type,
            operation=event.event_type,
            result="success",
        )
        return self._to_domain(model)

    async def list_by_review(
        self, review_id: UUID, offset: int, limit: int
    ) -> tuple[list[ReviewEvent], int]:
        filters = [ReviewEventModel.review_id == review_id]
        total = await self._session.scalar(
            select(func.count()).select_from(ReviewEventModel).where(*filters)
        )
        result = await self._session.execute(
            select(ReviewEventModel)
            .where(*filters)
            .order_by(ReviewEventModel.created_at.desc(), ReviewEventModel.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [self._to_domain(model) for model in result.scalars().all()], int(
            total or 0
        )

    async def get_reconciliation_run(self, run_id: UUID) -> ReviewEvent | None:
        result = await self._session.execute(
            select(ReviewEventModel).where(
                ReviewEventModel.run_id == run_id,
                ReviewEventModel.event_type == "RECONCILIATION_RUN",
            )
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_orphan_detection(self, fingerprint: str) -> ReviewEvent | None:
        """Find the first persisted detection for one opaque orphan id."""
        result = await self._session.execute(
            select(ReviewEventModel)
            .where(
                ReviewEventModel.resource_type == "ORPHAN_FILE",
                ReviewEventModel.event_type == "ORPHAN_DETECTED",
                ReviewEventModel.resource_id == fingerprint,
            )
            .order_by(ReviewEventModel.created_at.asc(), ReviewEventModel.id.asc())
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    @staticmethod
    def _to_domain(model: ReviewEventModel) -> ReviewEvent:
        return ReviewEvent(
            id=model.id,
            resource_type=model.resource_type,
            event_type=model.event_type,
            created_at=model.created_at,
            review_id=model.review_id,
            draft_id=model.draft_id,
            export_id=model.export_id,
            attempt_id=model.attempt_id,
            resource_id=model.resource_id,
            actor=model.actor,
            request_id=model.request_id,
            run_id=model.run_id,
            draft_version=model.draft_version,
            summary=model.summary,
        )
