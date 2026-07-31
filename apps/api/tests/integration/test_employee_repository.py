"""Integration tests for employee repository."""

import uuid
from datetime import UTC, datetime

import pytest

from legal_ai.adapters.database.employee_repository import (
    SQLAlchemyEmployeeRepository,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.domain.employee import Employee
from legal_ai.domain.enums import DocumentType


@pytest.fixture
async def session():
    """Create a test database session."""
    from sqlalchemy.ext.asyncio import AsyncSession

    engine = create_engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
        await session.rollback()


@pytest.fixture
def repo(session):
    """Create employee repository."""
    return SQLAlchemyEmployeeRepository(session)


def _unique_doc_number() -> str:
    """Generate a unique 8-digit document number."""
    return str(uuid.uuid4().int)[:8]


@pytest.mark.integration
class TestEmployeeRepository:
    """Integration tests for employee repository."""

    async def test_create_and_get_by_id(self, repo):
        employee = Employee(
            id=uuid.uuid4(),
            employee_number=f"LEG-{uuid.uuid4().hex[:8]}",
            first_name="Test",
            last_name="User",
            document_type=DocumentType.DNI,
            document_number=_unique_doc_number(),
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        created = await repo.create(employee)
        retrieved = await repo.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.employee_number == employee.employee_number

    async def test_get_by_employee_number(self, repo):
        emp_num = f"LEG-{uuid.uuid4().hex[:8]}"
        employee = Employee(
            id=uuid.uuid4(),
            employee_number=emp_num,
            first_name="Test",
            last_name="User",
            document_type=DocumentType.DNI,
            document_number=_unique_doc_number(),
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await repo.create(employee)
        retrieved = await repo.get_by_employee_number(emp_num)
        assert retrieved is not None
        assert retrieved.employee_number == emp_num

    async def test_get_by_document(self, repo):
        doc_num = _unique_doc_number()
        employee = Employee(
            id=uuid.uuid4(),
            employee_number=f"LEG-{uuid.uuid4().hex[:8]}",
            first_name="Test",
            last_name="User",
            document_type=DocumentType.DNI,
            document_number=doc_num,
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await repo.create(employee)
        retrieved = await repo.get_by_document("dni", doc_num)
        assert retrieved is not None

    async def test_list_with_pagination(self, repo):
        for i in range(5):
            employee = Employee(
                id=uuid.uuid4(),
                employee_number=f"LEG-{uuid.uuid4().hex[:8]}",
                first_name=f"User{i}",
                last_name="Test",
                document_type=DocumentType.DNI,
                document_number=_unique_doc_number(),
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            await repo.create(employee)

        employees, total = await repo.list(page=1, page_size=2)
        assert len(employees) <= 2
        assert total >= 5

    async def test_deactivate(self, repo):
        employee = Employee(
            id=uuid.uuid4(),
            employee_number=f"LEG-{uuid.uuid4().hex[:8]}",
            first_name="Test",
            last_name="User",
            document_type=DocumentType.DNI,
            document_number=_unique_doc_number(),
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        created = await repo.create(employee)
        deactivated = await repo.deactivate(created.id)
        assert deactivated is not None
        assert deactivated.active is False

    async def test_deactivate_idempotent(self, repo):
        employee = Employee(
            id=uuid.uuid4(),
            employee_number=f"LEG-{uuid.uuid4().hex[:8]}",
            first_name="Test",
            last_name="User",
            document_type=DocumentType.DNI,
            document_number=_unique_doc_number(),
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        created = await repo.create(employee)
        await repo.deactivate(created.id)
        result = await repo.deactivate(created.id)
        assert result is not None
        assert result.active is False

    async def test_get_by_cuil(self, repo):
        cuil = "20301112223"
        employee = Employee(
            id=uuid.uuid4(),
            employee_number=f"LEG-{uuid.uuid4().hex[:8]}",
            first_name="CUIL",
            last_name="Test",
            document_type=DocumentType.DNI,
            document_number=_unique_doc_number(),
            cuil=cuil,
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await repo.create(employee)
        retrieved = await repo.get_by_cuil(cuil)
        assert retrieved is not None
        assert retrieved.cuil == cuil

    async def test_get_by_cuil_not_found(self, repo):
        retrieved = await repo.get_by_cuil("00000000000")
        assert retrieved is None

    async def test_list_with_query_filter(self, repo):
        unique_token = uuid.uuid4().hex[:8]
        employee = Employee(
            id=uuid.uuid4(),
            employee_number=f"QRY-{unique_token}",
            first_name="Query",
            last_name="Filter",
            document_type=DocumentType.DNI,
            document_number=_unique_doc_number(),
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await repo.create(employee)
        employees, total = await repo.list(page=1, page_size=20, query=unique_token)
        assert any(e.employee_number == f"QRY-{unique_token}" for e in employees)

    async def test_list_with_active_filter(self, repo):
        emp_active = Employee(
            id=uuid.uuid4(),
            employee_number=f"ACT-{uuid.uuid4().hex[:8]}",
            first_name="Active",
            last_name="User",
            document_type=DocumentType.DNI,
            document_number=_unique_doc_number(),
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await repo.create(emp_active)
        employees, _ = await repo.list(page=1, page_size=20, active=True)
        assert all(e.active for e in employees)

    async def test_list_with_department_filter(self, repo):
        dept = f"Dept-{uuid.uuid4().hex[:6]}"
        employee = Employee(
            id=uuid.uuid4(),
            employee_number=f"DEP-{uuid.uuid4().hex[:8]}",
            first_name="Dept",
            last_name="User",
            document_type=DocumentType.DNI,
            document_number=_unique_doc_number(),
            department=dept,
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await repo.create(employee)
        employees, _ = await repo.list(page=1, page_size=20, department=dept)
        assert any(e.department == dept for e in employees)

    async def test_update(self, repo):
        employee = Employee(
            id=uuid.uuid4(),
            employee_number=f"UPD-{uuid.uuid4().hex[:8]}",
            first_name="Original",
            last_name="Name",
            document_type=DocumentType.DNI,
            document_number=_unique_doc_number(),
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        created = await repo.create(employee)
        created.first_name = "Updated"
        created.email = "updated@example.com"
        updated = await repo.update(created)
        assert updated.first_name == "Updated"
        assert updated.email == "updated@example.com"

    async def test_deactivate_nonexistent(self, repo):
        result = await repo.deactivate(uuid.uuid4())
        assert result is None
