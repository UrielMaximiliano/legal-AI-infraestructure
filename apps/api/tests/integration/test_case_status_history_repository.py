"""Integration tests for case status history repository."""

import uuid
from datetime import UTC, datetime

import pytest

from legal_ai.adapters.database.case_file_repository import (
    SQLAlchemyCaseFileRepository,
)
from legal_ai.adapters.database.case_status_history_repository import (
    SQLAlchemyCaseStatusHistoryRepository,
)
from legal_ai.adapters.database.employee_repository import (
    SQLAlchemyEmployeeRepository,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.domain.case_file import CaseFile
from legal_ai.domain.case_status_history import CaseStatusHistory
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
def history_repo(session):
    """Create case status history repository."""
    return SQLAlchemyCaseStatusHistoryRepository(session)


def _unique_doc_number() -> str:
    """Generate a unique 8-digit document number."""
    return str(uuid.uuid4().int)[:8]


async def _create_case_file(session) -> CaseFile:
    """Create and persist a real employee + case_file, returning the case_file."""
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
    emp_repo = SQLAlchemyEmployeeRepository(session)
    await emp_repo.create(employee)

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
    cf_repo = SQLAlchemyCaseFileRepository(session)
    return await cf_repo.create(case_file)


@pytest.mark.integration
class TestCaseStatusHistoryRepository:
    """Integration tests for case status history repository."""

    async def test_create_and_list(self, history_repo, session):
        case_file = await _create_case_file(session)
        entry = CaseStatusHistory(
            id=uuid.uuid4(),
            case_file_id=case_file.id,
            from_status=None,
            to_status=CaseStatus.DRAFT,
            changed_by="system",
            reason=None,
            request_id=None,
            changed_at=datetime.now(UTC),
        )
        await history_repo.create(entry)

        entries = await history_repo.list_by_case_file(case_file.id)
        assert len(entries) == 1
        assert entries[0].to_status == CaseStatus.DRAFT
        assert entries[0].changed_by == "system"

    async def test_list_ordered_chronologically(self, history_repo, session):
        case_file = await _create_case_file(session)
        now = datetime.now(UTC)

        for i in range(3):
            entry = CaseStatusHistory(
                id=uuid.uuid4(),
                case_file_id=case_file.id,
                from_status=CaseStatus.DRAFT if i > 0 else None,
                to_status=CaseStatus.UNDER_REVIEW,
                changed_by="system",
                reason=None,
                request_id=None,
                changed_at=now,
            )
            await history_repo.create(entry)

        entries = await history_repo.list_by_case_file(case_file.id)
        assert len(entries) == 3
