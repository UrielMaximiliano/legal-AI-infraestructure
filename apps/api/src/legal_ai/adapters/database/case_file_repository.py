"""SQLAlchemy case file repository implementation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import CaseFileModel
from legal_ai.domain.case_file import CaseFile
from legal_ai.domain.enums import CaseStatus, CaseType


class SQLAlchemyCaseFileRepository:
    """SQLAlchemy implementation of case file repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, case_file: CaseFile) -> CaseFile:
        model = CaseFileModel(
            id=case_file.id,
            case_number=case_file.case_number,
            employee_id=case_file.employee_id,
            title=case_file.title,
            description=case_file.description,
            case_type=case_file.case_type,
            status=case_file.status,
            version=case_file.version,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get_by_id(self, case_file_id: UUID) -> CaseFile | None:
        result = await self._session.execute(
            select(CaseFileModel).where(CaseFileModel.id == case_file_id)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_by_case_number(self, number: str) -> CaseFile | None:
        result = await self._session.execute(
            select(CaseFileModel).where(CaseFileModel.case_number == number)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def list(
        self,
        page: int,
        page_size: int,
        query: str | None = None,
        employee_id: UUID | None = None,
        status: str | None = None,
        case_type: str | None = None,
        opened_from: datetime | None = None,
        opened_to: datetime | None = None,
    ) -> tuple[list[CaseFile], int]:
        stmt = select(CaseFileModel)

        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(
                CaseFileModel.case_number.ilike(pattern)
                | CaseFileModel.title.ilike(pattern)
            )

        if employee_id:
            stmt = stmt.where(CaseFileModel.employee_id == employee_id)

        if status:
            stmt = stmt.where(CaseFileModel.status == status)

        if case_type:
            stmt = stmt.where(CaseFileModel.case_type == case_type)

        if opened_from:
            stmt = stmt.where(CaseFileModel.opened_at >= opened_from)

        if opened_to:
            stmt = stmt.where(CaseFileModel.opened_at <= opened_to)

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar() or 0

        # Apply pagination
        stmt = stmt.order_by(CaseFileModel.created_at.desc(), CaseFileModel.id.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self._session.execute(stmt)
        models = result.scalars().all()

        return [self._to_domain(m) for m in models], total

    async def update(self, case_file: CaseFile) -> CaseFile:
        result = await self._session.execute(
            select(CaseFileModel).where(CaseFileModel.id == case_file.id)
        )
        model = result.scalars().one()
        model.title = case_file.title
        model.description = case_file.description
        model.status = case_file.status
        model.version = case_file.version
        model.updated_at = case_file.updated_at
        model.closed_at = case_file.closed_at
        await self._session.flush()
        return self._to_domain(model)

    @staticmethod
    def _to_domain(model: CaseFileModel) -> CaseFile:
        return CaseFile(
            id=model.id,
            case_number=model.case_number,
            employee_id=model.employee_id,
            title=model.title,
            description=model.description,
            case_type=CaseType(model.case_type),
            status=CaseStatus(model.status),
            version=model.version,
            opened_at=model.opened_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
            closed_at=model.closed_at,
        )
