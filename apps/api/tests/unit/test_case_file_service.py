"""Unit tests for CaseFileService with mocked repositories."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from legal_ai.application.case_file_service import (
    CaseFileArchivedError,
    CaseFileEmployeeInactiveError,
    CaseFileEmployeeNotFoundError,
    CaseFileNotFoundError,
    CaseFileService,
    ConcurrentModificationError,
    InvalidStatusTransitionError,
)
from legal_ai.domain.case_file import CaseFile
from legal_ai.domain.enums import CaseStatus, CaseType


def _cf(**overrides) -> CaseFile:
    defaults = dict(
        id=uuid4(),
        case_number="CF-2026-0001",
        employee_id=uuid4(),
        title="Designación de abogado",
        description="Caso de diseño",
        case_type=CaseType.DESIGNACION,
        status=CaseStatus.DRAFT,
        version=1,
        opened_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=None,
        closed_at=None,
    )
    defaults.update(overrides)
    return CaseFile(**defaults)


class FakeUoW:
    def __init__(self) -> None:
        self.employees = AsyncMock()
        self.case_files = AsyncMock()
        self.case_status_history = AsyncMock()


@pytest.fixture
def uow() -> FakeUoW:
    return FakeUoW()


@pytest.fixture
def service(uow: FakeUoW) -> CaseFileService:
    return CaseFileService(uow=uow)


class TestCreate:
    @pytest.mark.anyio
    async def test_create_with_valid_employee(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf()
        emp_mock = AsyncMock()
        emp_mock.active = True
        uow.employees.get_by_id = AsyncMock(return_value=emp_mock)
        uow.case_files.create = AsyncMock(return_value=cf)
        uow.case_status_history.create = AsyncMock()
        result = await service.create(
            employee_id=cf.employee_id,
            title="Designación",
            case_type="designacion",
        )
        assert result == cf
        uow.case_files.create.assert_awaited_once()
        uow.case_status_history.create.assert_awaited_once()

    @pytest.mark.anyio
    async def test_create_with_description(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(description="Detailed description")
        emp_mock = AsyncMock()
        emp_mock.active = True
        uow.employees.get_by_id = AsyncMock(return_value=emp_mock)
        uow.case_files.create = AsyncMock(return_value=cf)
        uow.case_status_history.create = AsyncMock()
        result = await service.create(
            employee_id=cf.employee_id,
            title="Test",
            case_type="designacion",
            description="Detailed description",
        )
        assert result.description == "Detailed description"

    @pytest.mark.anyio
    async def test_create_with_request_id(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf()
        emp_mock = AsyncMock()
        emp_mock.active = True
        uow.employees.get_by_id = AsyncMock(return_value=emp_mock)
        uow.case_files.create = AsyncMock(return_value=cf)
        uow.case_status_history.create = AsyncMock()
        await service.create(
            employee_id=cf.employee_id,
            title="Test",
            case_type="designacion",
            request_id="req-123",
        )
        history_call = uow.case_status_history.create.call_args[0][0]
        assert history_call.request_id == "req-123"

    @pytest.mark.anyio
    async def test_create_employee_not_found(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        uow.employees.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(CaseFileEmployeeNotFoundError):
            await service.create(
                employee_id=uuid4(),
                title="Test",
                case_type="designacion",
            )

    @pytest.mark.anyio
    async def test_create_employee_inactive(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        emp_mock = AsyncMock()
        emp_mock.active = False
        uow.employees.get_by_id = AsyncMock(return_value=emp_mock)
        with pytest.raises(CaseFileEmployeeInactiveError):
            await service.create(
                employee_id=uuid4(),
                title="Test",
                case_type="designacion",
            )


class TestGetById:
    @pytest.mark.anyio
    async def test_found(self, service: CaseFileService, uow: FakeUoW) -> None:
        cf = _cf()
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        result = await service.get_by_id(cf.id)
        assert result == cf

    @pytest.mark.anyio
    async def test_not_found(self, service: CaseFileService, uow: FakeUoW) -> None:
        uow.case_files.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(CaseFileNotFoundError):
            await service.get_by_id(uuid4())


class TestList:
    @pytest.mark.anyio
    async def test_list_default(self, service: CaseFileService, uow: FakeUoW) -> None:
        cf = _cf()
        uow.case_files.list = AsyncMock(return_value=([cf], 1))
        case_files, total = await service.list(page=1, page_size=20)
        assert case_files == [cf]
        assert total == 1

    @pytest.mark.anyio
    async def test_list_with_filters(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf()
        uow.case_files.list = AsyncMock(return_value=([cf], 1))
        emp_id = uuid4()
        case_files, total = await service.list(
            page=2,
            page_size=10,
            employee_id=emp_id,
            status="draft",
            case_type="designacion",
        )
        assert case_files == [cf]
        assert total == 1


class TestUpdate:
    @pytest.mark.anyio
    async def test_update_fields(self, service: CaseFileService, uow: FakeUoW) -> None:
        cf = _cf()
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        uow.case_files.update = AsyncMock(return_value=cf)
        result = await service.update(cf.id, title="Nuevo título", description="Nueva")
        assert result == cf
        uow.case_files.update.assert_awaited_once()

    @pytest.mark.anyio
    async def test_update_not_found(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        uow.case_files.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(CaseFileNotFoundError):
            await service.update(uuid4(), title="X")

    @pytest.mark.anyio
    async def test_update_archived_blocked(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.ARCHIVED)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        with pytest.raises(CaseFileArchivedError):
            await service.update(cf.id, title="X")

    @pytest.mark.anyio
    async def test_update_optimistic_locking(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(version=2)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        with pytest.raises(ConcurrentModificationError):
            await service.update(cf.id, title="X", expected_version=1)

    @pytest.mark.anyio
    async def test_update_unchanged_description(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(description="old")
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        uow.case_files.update = AsyncMock(return_value=cf)
        result = await service.update(cf.id, title="New title")
        assert result.description == "old"


class TestTransition:
    @pytest.mark.anyio
    async def test_valid_transition(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.DRAFT, version=1)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        cf_updated = _cf(status=CaseStatus.UNDER_REVIEW, version=2)
        uow.case_files.update = AsyncMock(return_value=cf_updated)
        uow.case_status_history.create = AsyncMock()
        result = await service.transition(
            cf.id,
            status=CaseStatus.UNDER_REVIEW,
            expected_version=1,
            changed_by="user@test.com",
        )
        assert result.status == CaseStatus.UNDER_REVIEW

    @pytest.mark.anyio
    async def test_invalid_transition(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.DRAFT, version=1)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        with pytest.raises(InvalidStatusTransitionError):
            await service.transition(
                cf.id,
                status=CaseStatus.ARCHIVED,
                expected_version=1,
                changed_by="user@test.com",
            )

    @pytest.mark.anyio
    async def test_transition_archived_blocked(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.ARCHIVED, version=1)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        with pytest.raises(CaseFileArchivedError):
            await service.transition(
                cf.id,
                status=CaseStatus.DRAFT,
                expected_version=1,
                changed_by="user@test.com",
            )

    @pytest.mark.anyio
    async def test_transition_not_found(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        uow.case_files.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(CaseFileNotFoundError):
            await service.transition(
                uuid4(),
                status=CaseStatus.UNDER_REVIEW,
                expected_version=1,
                changed_by="user@test.com",
            )

    @pytest.mark.anyio
    async def test_transition_optimistic_locking(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.DRAFT, version=2)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        with pytest.raises(ConcurrentModificationError):
            await service.transition(
                cf.id,
                status=CaseStatus.UNDER_REVIEW,
                expected_version=1,
                changed_by="user@test.com",
            )

    @pytest.mark.anyio
    async def test_transition_to_archived_sets_closed_at(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.APPROVED, version=1)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        cf_closed = _cf(
            status=CaseStatus.ARCHIVED, version=2, closed_at=datetime.now(UTC)
        )
        uow.case_files.update = AsyncMock(return_value=cf_closed)
        uow.case_status_history.create = AsyncMock()
        result = await service.transition(
            cf.id,
            status=CaseStatus.ARCHIVED,
            expected_version=1,
            changed_by="user@test.com",
        )
        assert result.status == CaseStatus.ARCHIVED

    @pytest.mark.anyio
    async def test_transition_creates_history(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.DRAFT, version=1)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        cf_updated = _cf(status=CaseStatus.UNDER_REVIEW, version=2)
        uow.case_files.update = AsyncMock(return_value=cf_updated)
        uow.case_status_history.create = AsyncMock()
        await service.transition(
            cf.id,
            status=CaseStatus.UNDER_REVIEW,
            expected_version=1,
            changed_by="user@test.com",
            reason="Revisión inicial",
            request_id="req-456",
        )
        history_call = uow.case_status_history.create.call_args[0][0]
        assert history_call.reason == "Revisión inicial"
        assert history_call.request_id == "req-456"

    @pytest.mark.anyio
    async def test_transition_under_review_to_in_process(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.UNDER_REVIEW, version=1)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        cf_updated = _cf(status=CaseStatus.IN_PROCESS, version=2)
        uow.case_files.update = AsyncMock(return_value=cf_updated)
        uow.case_status_history.create = AsyncMock()
        result = await service.transition(
            cf.id,
            status=CaseStatus.IN_PROCESS,
            expected_version=1,
            changed_by="user@test.com",
        )
        assert result.status == CaseStatus.IN_PROCESS

    @pytest.mark.anyio
    async def test_transition_in_process_to_submitted(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.IN_PROCESS, version=1)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        cf_updated = _cf(status=CaseStatus.SUBMITTED, version=2)
        uow.case_files.update = AsyncMock(return_value=cf_updated)
        uow.case_status_history.create = AsyncMock()
        result = await service.transition(
            cf.id,
            status=CaseStatus.SUBMITTED,
            expected_version=1,
            changed_by="user@test.com",
        )
        assert result.status == CaseStatus.SUBMITTED

    @pytest.mark.anyio
    async def test_transition_submitted_to_approved(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.SUBMITTED, version=1)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        cf_updated = _cf(status=CaseStatus.APPROVED, version=2)
        uow.case_files.update = AsyncMock(return_value=cf_updated)
        uow.case_status_history.create = AsyncMock()
        result = await service.transition(
            cf.id,
            status=CaseStatus.APPROVED,
            expected_version=1,
            changed_by="user@test.com",
        )
        assert result.status == CaseStatus.APPROVED

    @pytest.mark.anyio
    async def test_transition_submitted_to_rejected(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        cf = _cf(status=CaseStatus.SUBMITTED, version=1)
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        cf_updated = _cf(status=CaseStatus.REJECTED, version=2)
        uow.case_files.update = AsyncMock(return_value=cf_updated)
        uow.case_status_history.create = AsyncMock()
        result = await service.transition(
            cf.id,
            status=CaseStatus.REJECTED,
            expected_version=1,
            changed_by="user@test.com",
        )
        assert result.status == CaseStatus.REJECTED


class TestGetHistory:
    @pytest.mark.anyio
    async def test_get_history(self, service: CaseFileService, uow: FakeUoW) -> None:
        cf = _cf()
        uow.case_files.get_by_id = AsyncMock(return_value=cf)
        history = [
            {"from_status": "draft", "to_status": "en_revision", "at": "2026-01-01"}
        ]
        uow.case_status_history.list_by_case_file = AsyncMock(return_value=history)
        result = await service.get_history(cf.id)
        assert result == history

    @pytest.mark.anyio
    async def test_get_history_not_found(
        self, service: CaseFileService, uow: FakeUoW
    ) -> None:
        uow.case_files.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(CaseFileNotFoundError):
            await service.get_history(uuid4())
