"""Integration tests for case file repository."""

import uuid
from datetime import UTC, datetime

import pytest

from legal_ai.adapters.database.case_file_repository import (
    SQLAlchemyCaseFileRepository,
)
from legal_ai.adapters.database.employee_repository import (
    SQLAlchemyEmployeeRepository,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.domain.case_file import CaseFile
from legal_ai.domain.employee import Employee
from legal_ai.domain.enums import CaseStatus, CaseType, DocumentType


@pytest.fixture
async def session():
    """Create a test database session."""
    from sqlalchemy.ext.asyncio import AsyncSession

    engine = create_engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
        await session.rollback()


@pytest.fixture
def case_file_repo(session):
    """Create case file repository."""
    return SQLAlchemyCaseFileRepository(session)


@pytest.fixture
def employee_repo(session):
    """Create employee repository."""
    return SQLAlchemyEmployeeRepository(session)


def _unique_doc_number() -> str:
    """Generate a unique 8-digit document number."""
    return str(uuid.uuid4().int)[:8]


async def _create_employee(employee_repo) -> Employee:
    """Create and persist a test employee, returning it."""
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
    return await employee_repo.create(employee)


@pytest.mark.integration
class TestCaseFileRepository:
    """Integration tests for case file repository."""

    async def test_create_and_get_by_id(self, case_file_repo, employee_repo):
        employee = await _create_employee(employee_repo)
        case_file = CaseFile(
            id=uuid.uuid4(),
            case_number=f"CF-{uuid.uuid4()}",
            employee_id=employee.id,
            title="Test Case",
            case_type=CaseType.DESIGNACION,
            status=CaseStatus.DRAFT,
            version=1,
            opened_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        created = await case_file_repo.create(case_file)
        retrieved = await case_file_repo.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.case_number == case_file.case_number

    async def test_get_by_case_number(self, case_file_repo, employee_repo):
        employee = await _create_employee(employee_repo)
        case_number = f"CF-{uuid.uuid4()}"
        case_file = CaseFile(
            id=uuid.uuid4(),
            case_number=case_number,
            employee_id=employee.id,
            title="Test Case",
            case_type=CaseType.DESIGNACION,
            status=CaseStatus.DRAFT,
            version=1,
            opened_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await case_file_repo.create(case_file)
        retrieved = await case_file_repo.get_by_case_number(case_number)
        assert retrieved is not None

    async def test_list_with_filters(self, case_file_repo, employee_repo):
        employee = await _create_employee(employee_repo)
        case_file = CaseFile(
            id=uuid.uuid4(),
            case_number=f"CF-{uuid.uuid4()}",
            employee_id=employee.id,
            title="Test Case",
            case_type=CaseType.DESIGNACION,
            status=CaseStatus.DRAFT,
            version=1,
            opened_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await case_file_repo.create(case_file)

        case_files, total = await case_file_repo.list(
            page=1, page_size=10, employee_id=employee.id
        )
        assert len(case_files) >= 1
        assert total >= 1

    async def test_update(self, case_file_repo, employee_repo):
        employee = await _create_employee(employee_repo)
        case_file = CaseFile(
            id=uuid.uuid4(),
            case_number=f"CF-{uuid.uuid4()}",
            employee_id=employee.id,
            title="Original Title",
            case_type=CaseType.DESIGNACION,
            status=CaseStatus.DRAFT,
            version=1,
            opened_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        created = await case_file_repo.create(case_file)
        created.title = "Updated Title"
        created.version = 2
        updated = await case_file_repo.update(created)
        assert updated.title == "Updated Title"
        assert updated.version == 2

    async def test_list_with_query_filter(self, case_file_repo, employee_repo):
        employee = await _create_employee(employee_repo)
        unique_token = uuid.uuid4().hex[:8]
        case_file = CaseFile(
            id=uuid.uuid4(),
            case_number=f"QRY-{unique_token}",
            employee_id=employee.id,
            title=f"Query Test {unique_token}",
            case_type=CaseType.DESIGNACION,
            status=CaseStatus.DRAFT,
            version=1,
            opened_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await case_file_repo.create(case_file)
        case_files, total = await case_file_repo.list(
            page=1, page_size=20, query=unique_token
        )
        assert any(
            unique_token in cf.title or unique_token in cf.case_number
            for cf in case_files
        )

    async def test_list_with_status_filter(self, case_file_repo, employee_repo):
        employee = await _create_employee(employee_repo)
        case_file = CaseFile(
            id=uuid.uuid4(),
            case_number=f"CF-{uuid.uuid4()}",
            employee_id=employee.id,
            title="Status Filter Test",
            case_type=CaseType.DESIGNACION,
            status=CaseStatus.DRAFT,
            version=1,
            opened_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await case_file_repo.create(case_file)
        case_files, _ = await case_file_repo.list(page=1, page_size=20, status="draft")
        assert all(cf.status == CaseStatus.DRAFT for cf in case_files)

    async def test_list_with_case_type_filter(self, case_file_repo, employee_repo):
        employee = await _create_employee(employee_repo)
        case_file = CaseFile(
            id=uuid.uuid4(),
            case_number=f"CF-{uuid.uuid4()}",
            employee_id=employee.id,
            title="Type Filter Test",
            case_type=CaseType.LICENCIA,
            status=CaseStatus.DRAFT,
            version=1,
            opened_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await case_file_repo.create(case_file)
        case_files, _ = await case_file_repo.list(
            page=1, page_size=20, case_type="licencia"
        )
        assert all(cf.case_type == CaseType.LICENCIA for cf in case_files)

    async def test_list_with_date_range_filter(self, case_file_repo, employee_repo):
        employee = await _create_employee(employee_repo)
        now = datetime.now(UTC)
        case_file = CaseFile(
            id=uuid.uuid4(),
            case_number=f"CF-{uuid.uuid4()}",
            employee_id=employee.id,
            title="Date Range Test",
            case_type=CaseType.DESIGNACION,
            status=CaseStatus.DRAFT,
            version=1,
            opened_at=now,
            created_at=now,
            updated_at=now,
        )
        await case_file_repo.create(case_file)
        case_files, _ = await case_file_repo.list(
            page=1,
            page_size=20,
            opened_from=now.replace(hour=0, minute=0, second=0),
            opened_to=now.replace(hour=23, minute=59, second=59),
        )
        assert len(case_files) >= 1

    async def test_list_empty_result(self, case_file_repo):
        case_files, total = await case_file_repo.list(page=1, page_size=20)
        assert isinstance(case_files, list)
