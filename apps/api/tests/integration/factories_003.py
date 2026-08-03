"""PostgreSQL-backed factories for increment 003 integration tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import CaseFileModel, EmployeeModel


async def create_case_file(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    employee_id = uuid.uuid4()
    case_file_id = uuid.uuid4()
    token = uuid.uuid4().hex[:10]
    employee = EmployeeModel(
        id=employee_id,
        employee_number=f"LEG-{token}",
        first_name="Integration",
        last_name="Test",
        document_type="dni",
        document_number=str(uuid.uuid4().int)[:8],
        active=True,
    )
    session.add(employee)
    await session.flush()
    session.add(
        CaseFileModel(
            id=case_file_id,
            case_number=f"EXP-{token}",
            employee_id=employee_id,
            title="Expediente de integración",
            case_type="designacion",
            status="draft",
            version=1,
            opened_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return case_file_id, employee_id
