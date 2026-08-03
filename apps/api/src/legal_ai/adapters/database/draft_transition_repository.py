"""SQLAlchemy draft transition repository implementation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import DraftTransitionModel
from legal_ai.domain.draft import DraftTransition
from legal_ai.domain.enums import DraftStatus, TransitionAction


class SQLAlchemyDraftTransitionRepository:
    """SQLAlchemy implementation of draft transition repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, transition: DraftTransition) -> DraftTransition:
        model = DraftTransitionModel(
            id=transition.id,
            draft_id=transition.draft_id,
            from_status=transition.from_status,
            to_status=transition.to_status,
            action=transition.action,
            observations=transition.observations,
            performed_by=transition.performed_by,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def list_by_draft(self, draft_id: UUID) -> list[DraftTransition]:
        result = await self._session.execute(
            select(DraftTransitionModel)
            .where(DraftTransitionModel.draft_id == draft_id)
            .order_by(
                DraftTransitionModel.created_at.asc(), DraftTransitionModel.id.asc()
            )
        )
        models = result.scalars().all()
        return [self._to_domain(m) for m in models]

    @staticmethod
    def _to_domain(model: DraftTransitionModel) -> DraftTransition:
        return DraftTransition(
            id=model.id,
            draft_id=model.draft_id,
            from_status=DraftStatus(model.from_status),
            to_status=DraftStatus(model.to_status),
            action=TransitionAction(model.action),
            observations=model.observations,
            performed_by=model.performed_by,
            created_at=model.created_at,
        )
