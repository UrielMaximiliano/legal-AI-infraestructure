"""SQLAlchemy case status history repository implementation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import CaseStatusHistoryModel
from legal_ai.domain.case_status_history import CaseStatusHistory
from legal_ai.domain.enums import CaseStatus


class SQLAlchemyCaseStatusHistoryRepository:
    """SQLAlchemy implementation of case status history repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entry: CaseStatusHistory) -> CaseStatusHistory:
        model = CaseStatusHistoryModel(
            id=entry.id,
            case_file_id=entry.case_file_id,
            from_status=entry.from_status,
            to_status=entry.to_status,
            changed_by=entry.changed_by,
            reason=entry.reason,
            request_id=entry.request_id,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def list_by_case_file(self, case_file_id: UUID) -> list[CaseStatusHistory]:
        result = await self._session.execute(
            select(CaseStatusHistoryModel)
            .where(CaseStatusHistoryModel.case_file_id == case_file_id)
            .order_by(
                CaseStatusHistoryModel.changed_at.asc(),
                CaseStatusHistoryModel.id.asc(),
            )
        )
        models = result.scalars().all()
        return [self._to_domain(m) for m in models]

    @staticmethod
    def _to_domain(model: CaseStatusHistoryModel) -> CaseStatusHistory:
        return CaseStatusHistory(
            id=model.id,
            case_file_id=model.case_file_id,
            from_status=CaseStatus(model.from_status) if model.from_status else None,
            to_status=CaseStatus(model.to_status),
            changed_by=model.changed_by,
            reason=model.reason,
            request_id=model.request_id,
            changed_at=model.changed_at,
        )
