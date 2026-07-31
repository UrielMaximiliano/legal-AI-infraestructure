"""Unit tests for EmployeeService with mocked repositories."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from legal_ai.application.employee_service import (
    EmployeeDocumentConflictError,
    EmployeeNotFoundError,
    EmployeeNumberConflictError,
    EmployeeService,
)
from legal_ai.domain.employee import Employee
from legal_ai.domain.enums import DocumentType


def _emp(**overrides) -> Employee:
    defaults = dict(
        id=uuid4(),
        employee_number="EMP-001",
        first_name="Juan",
        last_name="Pérez",
        document_type=DocumentType.DNI,
        document_number="30111222",
        cuil="20-30111222-3",
        email="juan@example.com",
        phone="+54 11 1234-5678",
        position="Abogado",
        department="Legal",
        active=True,
        created_at=datetime.now(UTC),
        updated_at=None,
    )
    defaults.update(overrides)
    return Employee(**defaults)


class FakeUoW:
    def __init__(self) -> None:
        self.employees = AsyncMock()
        self.case_files = AsyncMock()
        self.case_status_history = AsyncMock()


@pytest.fixture
def uow() -> FakeUoW:
    return FakeUoW()


@pytest.fixture
def service(uow: FakeUoW) -> EmployeeService:
    return EmployeeService(uow=uow)


class TestCreate:
    @pytest.mark.anyio
    async def test_create_all_fields(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        emp = _emp()
        uow.employees.get_by_employee_number = AsyncMock(return_value=None)
        uow.employees.get_by_document = AsyncMock(return_value=None)
        uow.employees.get_by_cuil = AsyncMock(return_value=None)
        uow.employees.create = AsyncMock(return_value=emp)
        result = await service.create(
            employee_number="EMP-001",
            first_name="Juan",
            last_name="Pérez",
            document_type=DocumentType.DNI,
            document_number="30111222",
            cuil="20-30111222-3",
            email="juan@example.com",
            phone="+54 11 1234-5678",
            position="Abogado",
            department="Legal",
        )
        assert result == emp
        uow.employees.create.assert_awaited_once()

    @pytest.mark.anyio
    async def test_create_minimal_fields(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        emp = _emp(cuil=None, email=None, phone=None, position=None, department=None)
        uow.employees.get_by_employee_number = AsyncMock(return_value=None)
        uow.employees.get_by_document = AsyncMock(return_value=None)
        uow.employees.create = AsyncMock(return_value=emp)
        result = await service.create(
            employee_number="EMP-001",
            first_name="Juan",
            last_name="Pérez",
            document_type=DocumentType.DNI,
            document_number="30111222",
        )
        assert result == emp

    @pytest.mark.anyio
    async def test_duplicate_employee_number(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        existing = _emp()
        uow.employees.get_by_employee_number = AsyncMock(return_value=existing)
        with pytest.raises(EmployeeNumberConflictError):
            await service.create(
                employee_number="EMP-001",
                first_name="Juan",
                last_name="Pérez",
                document_type=DocumentType.DNI,
                document_number="30111222",
            )

    @pytest.mark.anyio
    async def test_duplicate_document(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        uow.employees.get_by_employee_number = AsyncMock(return_value=None)
        existing_doc = _emp()
        uow.employees.get_by_document = AsyncMock(return_value=existing_doc)
        with pytest.raises(EmployeeDocumentConflictError):
            await service.create(
                employee_number="EMP-002",
                first_name="Juan",
                last_name="Pérez",
                document_type=DocumentType.DNI,
                document_number="30111222",
            )

    @pytest.mark.anyio
    async def test_duplicate_cuil(self, service: EmployeeService, uow: FakeUoW) -> None:
        uow.employees.get_by_employee_number = AsyncMock(return_value=None)
        uow.employees.get_by_document = AsyncMock(return_value=None)
        existing_cuil = _emp()
        uow.employees.get_by_cuil = AsyncMock(return_value=existing_cuil)
        with pytest.raises(EmployeeDocumentConflictError):
            await service.create(
                employee_number="EMP-003",
                first_name="Juan",
                last_name="Pérez",
                document_type=DocumentType.DNI,
                document_number="30999888",
                cuil="20-30999888-5",
            )


class TestGetById:
    @pytest.mark.anyio
    async def test_found(self, service: EmployeeService, uow: FakeUoW) -> None:
        emp = _emp()
        uow.employees.get_by_id = AsyncMock(return_value=emp)
        result = await service.get_by_id(emp.id)
        assert result == emp

    @pytest.mark.anyio
    async def test_not_found(self, service: EmployeeService, uow: FakeUoW) -> None:
        uow.employees.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(EmployeeNotFoundError):
            await service.get_by_id(uuid4())


class TestUpdate:
    @pytest.mark.anyio
    async def test_update_all_fields(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        emp = _emp()
        uow.employees.get_by_id = AsyncMock(return_value=emp)
        uow.employees.update = AsyncMock(return_value=emp)
        result = await service.update(
            emp.id,
            first_name="María",
            last_name="García",
            email="maria@example.com",
            phone="+54 11 9999-0000",
            position="Gerente",
            department="RRHH",
        )
        assert result == emp
        uow.employees.update.assert_awaited_once()

    @pytest.mark.anyio
    async def test_update_partial_fields(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        emp = _emp()
        uow.employees.get_by_id = AsyncMock(return_value=emp)
        uow.employees.update = AsyncMock(return_value=emp)
        result = await service.update(emp.id, first_name="María")
        assert result == emp

    @pytest.mark.anyio
    async def test_update_not_found(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        uow.employees.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(EmployeeNotFoundError):
            await service.update(uuid4(), first_name="María")

    @pytest.mark.anyio
    async def test_update_unchanged_fields(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        emp = _emp(email="old@example.com", phone="+54 11 0000-0000")
        uow.employees.get_by_id = AsyncMock(return_value=emp)
        uow.employees.update = AsyncMock(return_value=emp)
        result = await service.update(emp.id, first_name="María")
        assert result.email == "old@example.com"
        assert result.phone == "+54 11 0000-0000"


class TestDeactivate:
    @pytest.mark.anyio
    async def test_deactivate_success(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        emp = _emp(active=True)
        uow.employees.get_by_id = AsyncMock(return_value=emp)
        uow.employees.deactivate = AsyncMock(return_value=emp)
        result = await service.deactivate(emp.id)
        assert result == emp
        uow.employees.deactivate.assert_awaited_once()

    @pytest.mark.anyio
    async def test_deactivate_not_found(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        uow.employees.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(EmployeeNotFoundError):
            await service.deactivate(uuid4())


class TestList:
    @pytest.mark.anyio
    async def test_list_default(self, service: EmployeeService, uow: FakeUoW) -> None:
        emp = _emp()
        uow.employees.list = AsyncMock(return_value=([emp], 1))
        employees, total = await service.list(page=1, page_size=20)
        assert employees == [emp]
        assert total == 1

    @pytest.mark.anyio
    async def test_list_with_filters(
        self, service: EmployeeService, uow: FakeUoW
    ) -> None:
        emp = _emp()
        uow.employees.list = AsyncMock(return_value=([emp], 1))
        employees, total = await service.list(
            page=2, page_size=10, query="Pérez", active=True, department="Legal"
        )
        assert employees == [emp]
        assert total == 1
