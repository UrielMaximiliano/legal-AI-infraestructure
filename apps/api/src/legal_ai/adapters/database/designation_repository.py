"""SQLAlchemy designation repository implementation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import DesignationDataModel
from legal_ai.domain.designation_data import DesignationData


class SQLAlchemyDesignationRepository:
    """SQLAlchemy implementation of designation repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, designation: DesignationData) -> DesignationData:
        model = DesignationDataModel(
            id=designation.id,
            case_file_id=designation.case_file_id,
            position_name=designation.position_name,
            organizational_unit=designation.organizational_unit,
            start_date=designation.start_date,
            legal_basis=designation.legal_basis,
            appointing_authority=designation.appointing_authority,
            salary_category=designation.salary_category,
            work_schedule=designation.work_schedule,
            observations=designation.observations,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get_by_case_file_id(self, case_file_id: UUID) -> DesignationData | None:
        result = await self._session.execute(
            select(DesignationDataModel).where(
                DesignationDataModel.case_file_id == case_file_id
            )
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def update(self, designation: DesignationData) -> DesignationData:
        result = await self._session.execute(
            select(DesignationDataModel).where(
                DesignationDataModel.id == designation.id
            )
        )
        model = result.scalars().one()
        model.position_name = designation.position_name
        model.organizational_unit = designation.organizational_unit
        model.start_date = designation.start_date
        model.legal_basis = designation.legal_basis
        model.appointing_authority = designation.appointing_authority
        model.salary_category = designation.salary_category
        model.work_schedule = designation.work_schedule
        model.observations = designation.observations
        await self._session.flush()
        return self._to_domain(model)

    @staticmethod
    def _to_domain(model: DesignationDataModel) -> DesignationData:
        return DesignationData(
            id=model.id,
            case_file_id=model.case_file_id,
            position_name=model.position_name,
            organizational_unit=model.organizational_unit,
            start_date=model.start_date,
            legal_basis=model.legal_basis,
            appointing_authority=model.appointing_authority,
            salary_category=model.salary_category,
            work_schedule=model.work_schedule,
            observations=model.observations,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
