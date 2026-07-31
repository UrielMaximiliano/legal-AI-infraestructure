"""Integration tests for Unit of Work transactions."""

import uuid
from datetime import UTC, datetime

import pytest

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.case_file import CaseFile
from legal_ai.domain.case_status_history import CaseStatusHistory
from legal_ai.domain.employee import Employee
from legal_ai.domain.enums import CaseStatus, CaseType, DocumentType


def _unique_doc_number() -> str:
    """Generate a unique 8-digit document number."""
    return str(uuid.uuid4().int)[:8]


@pytest.mark.integration
class TestUnitOfWork:
    """Integration tests for Unit of Work."""

    async def test_commit_persists_changes(self):
        async with UnitOfWork() as uow:
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
            await uow.employees.create(employee)

        async with UnitOfWork() as uow:
            retrieved = await uow.employees.get_by_id(employee.id)
            assert retrieved is not None

    async def test_rollback_discards_changes(self):
        employee_id = uuid.uuid4()
        try:
            async with UnitOfWork() as uow:
                employee = Employee(
                    id=employee_id,
                    employee_number=f"LEG-{uuid.uuid4().hex[:8]}",
                    first_name="Test",
                    last_name="User",
                    document_type=DocumentType.DNI,
                    document_number=_unique_doc_number(),
                    active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                await uow.employees.create(employee)
                raise Exception("Force rollback")
        except Exception:
            pass

        async with UnitOfWork() as uow:
            retrieved = await uow.employees.get_by_id(employee_id)
            assert retrieved is None

    async def test_atomic_case_file_and_history(self):
        employee_id = uuid.uuid4()
        case_file_id = uuid.uuid4()

        async with UnitOfWork() as uow:
            employee = Employee(
                id=employee_id,
                employee_number=f"LEG-{uuid.uuid4().hex[:8]}",
                first_name="Test",
                last_name="User",
                document_type=DocumentType.DNI,
                document_number=_unique_doc_number(),
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            await uow.employees.create(employee)

            case_file = CaseFile(
                id=case_file_id,
                case_number=f"CF-{uuid.uuid4()}",
                employee_id=employee_id,
                title="Test Case",
                case_type=CaseType.DESIGNACION,
                status=CaseStatus.DRAFT,
                version=1,
                opened_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            await uow.case_files.create(case_file)

            history = CaseStatusHistory(
                id=uuid.uuid4(),
                case_file_id=case_file_id,
                from_status=None,
                to_status=CaseStatus.DRAFT,
                changed_by="system",
                reason=None,
                request_id=None,
                changed_at=datetime.now(UTC),
            )
            await uow.case_status_history.create(history)

        async with UnitOfWork() as uow:
            retrieved_cf = await uow.case_files.get_by_id(case_file_id)
            assert retrieved_cf is not None
            history_entries = await uow.case_status_history.list_by_case_file(
                case_file_id
            )
            assert len(history_entries) == 1
