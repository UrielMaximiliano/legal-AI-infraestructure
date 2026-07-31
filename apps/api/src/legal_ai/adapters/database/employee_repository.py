"""SQLAlchemy employee repository implementation."""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import EmployeeModel
from legal_ai.domain.employee import Employee
from legal_ai.domain.enums import DocumentType


class SQLAlchemyEmployeeRepository:
    """SQLAlchemy implementation of employee repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, employee: Employee) -> Employee:
        model = EmployeeModel(
            id=employee.id,
            employee_number=employee.employee_number,
            first_name=employee.first_name,
            last_name=employee.last_name,
            document_type=employee.document_type,
            document_number=employee.document_number,
            cuil=employee.cuil,
            email=employee.email,
            phone=employee.phone,
            position=employee.position,
            department=employee.department,
            active=employee.active,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get_by_id(self, employee_id: UUID) -> Employee | None:
        result = await self._session.execute(
            select(EmployeeModel).where(EmployeeModel.id == employee_id)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_by_employee_number(self, number: str) -> Employee | None:
        result = await self._session.execute(
            select(EmployeeModel).where(EmployeeModel.employee_number == number)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_by_document(self, doc_type: str, doc_number: str) -> Employee | None:
        result = await self._session.execute(
            select(EmployeeModel).where(
                EmployeeModel.document_type == doc_type,
                EmployeeModel.document_number == doc_number,
            )
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_by_cuil(self, cuil: str) -> Employee | None:
        result = await self._session.execute(
            select(EmployeeModel).where(EmployeeModel.cuil == cuil)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def list(
        self,
        page: int,
        page_size: int,
        query: str | None = None,
        active: bool | None = None,
        department: str | None = None,
    ) -> tuple[list[Employee], int]:
        stmt = select(EmployeeModel)

        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(
                EmployeeModel.employee_number.ilike(pattern)
                | EmployeeModel.first_name.ilike(pattern)
                | EmployeeModel.last_name.ilike(pattern)
                | EmployeeModel.document_number.ilike(pattern)
            )

        if active is not None:
            stmt = stmt.where(EmployeeModel.active == active)

        if department:
            stmt = stmt.where(EmployeeModel.department.ilike(f"%{department}%"))

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar() or 0

        # Apply pagination
        stmt = stmt.order_by(EmployeeModel.created_at.desc(), EmployeeModel.id.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self._session.execute(stmt)
        models = result.scalars().all()

        return [self._to_domain(m) for m in models], total

    async def update(self, employee: Employee) -> Employee:
        result = await self._session.execute(
            select(EmployeeModel).where(EmployeeModel.id == employee.id)
        )
        model = result.scalars().one()
        model.first_name = employee.first_name
        model.last_name = employee.last_name
        model.email = employee.email
        model.phone = employee.phone
        model.position = employee.position
        model.department = employee.department
        model.updated_at = employee.updated_at
        await self._session.flush()
        return self._to_domain(model)

    async def deactivate(self, employee_id: UUID) -> Employee | None:
        result = await self._session.execute(
            select(EmployeeModel).where(EmployeeModel.id == employee_id)
        )
        model = result.scalars().first()
        if model is None:
            return None
        if model.active:
            from datetime import datetime

            model.active = False
            model.updated_at = datetime.now(UTC)
            await self._session.flush()
        return self._to_domain(model)

    @staticmethod
    def _to_domain(model: EmployeeModel) -> Employee:
        return Employee(
            id=model.id,
            employee_number=model.employee_number,
            first_name=model.first_name,
            last_name=model.last_name,
            document_type=DocumentType(model.document_type),
            document_number=model.document_number,
            cuil=model.cuil,
            email=model.email,
            phone=model.phone,
            position=model.position,
            department=model.department,
            active=model.active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
