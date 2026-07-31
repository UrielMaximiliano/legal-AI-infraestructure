"""Unit tests for API exception handlers."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from legal_ai.api.exceptions import (
    conflict_error_handler,
    generic_error_handler,
    not_found_error_handler,
    validation_error_handler,
)
from legal_ai.application.case_file_service import (
    CaseFileArchivedError,
    CaseFileEmployeeInactiveError,
    CaseFileEmployeeNotFoundError,
    CaseFileNotFoundError,
    ConcurrentModificationError,
    InvalidStatusTransitionError,
)
from legal_ai.application.employee_service import (
    EmployeeDocumentConflictError,
    EmployeeNotFoundError,
    EmployeeNumberConflictError,
)
from legal_ai.domain.enums import CaseStatus


def _make_request(request_id: str | None = None) -> MagicMock:
    request = MagicMock()
    request.state.request_id = request_id
    return request


class TestNotFoundErrorHandler:
    @pytest.mark.anyio
    async def test_employee_not_found(self) -> None:
        exc = EmployeeNotFoundError(uuid4())
        result = await not_found_error_handler(_make_request("req-1"), exc)
        assert result.status_code == 404
        body = result.body
        assert b"EMPLOYEE_NOT_FOUND" in body

    @pytest.mark.anyio
    async def test_case_file_not_found(self) -> None:
        exc = CaseFileNotFoundError(uuid4())
        result = await not_found_error_handler(_make_request("req-2"), exc)
        assert result.status_code == 404
        assert b"CASE_FILE_NOT_FOUND" in result.body

    @pytest.mark.anyio
    async def test_case_file_employee_not_found(self) -> None:
        exc = CaseFileEmployeeNotFoundError(uuid4())
        result = await not_found_error_handler(_make_request("req-3"), exc)
        assert result.status_code == 404
        assert b"EMPLOYEE_NOT_FOUND" in result.body

    @pytest.mark.anyio
    async def test_unhandled_exception_returns_500(self) -> None:
        exc = RuntimeError("unexpected")
        result = await not_found_error_handler(_make_request("req-4"), exc)
        assert result.status_code == 500
        assert b"DATABASE_ERROR" in result.body

    @pytest.mark.anyio
    async def test_request_id_in_response(self) -> None:
        exc = EmployeeNotFoundError(uuid4())
        result = await not_found_error_handler(_make_request("req-5"), exc)
        assert b"req-5" in result.body


class TestConflictErrorHandler:
    @pytest.mark.anyio
    async def test_employee_number_conflict(self) -> None:
        exc = EmployeeNumberConflictError("EMP-001")
        result = await conflict_error_handler(_make_request("req-1"), exc)
        assert result.status_code == 409
        assert b"EMPLOYEE_NUMBER_CONFLICT" in result.body
        assert b"employee_number" in result.body

    @pytest.mark.anyio
    async def test_employee_document_conflict(self) -> None:
        exc = EmployeeDocumentConflictError("document_number", "document_number")
        result = await conflict_error_handler(_make_request("req-2"), exc)
        assert result.status_code == 409
        assert b"EMPLOYEE_DOCUMENT_CONFLICT" in result.body

    @pytest.mark.anyio
    async def test_case_file_archived(self) -> None:
        exc = CaseFileArchivedError(uuid4())
        result = await conflict_error_handler(_make_request("req-3"), exc)
        assert result.status_code == 409
        assert b"CASE_FILE_ARCHIVED" in result.body

    @pytest.mark.anyio
    async def test_concurrent_modification(self) -> None:
        exc = ConcurrentModificationError(uuid4())
        result = await conflict_error_handler(_make_request("req-4"), exc)
        assert result.status_code == 409
        assert b"CONCURRENT_MODIFICATION" in result.body

    @pytest.mark.anyio
    async def test_invalid_status_transition(self) -> None:
        exc = InvalidStatusTransitionError(CaseStatus.DRAFT, CaseStatus.ARCHIVED)
        result = await conflict_error_handler(_make_request("req-5"), exc)
        assert result.status_code == 409
        assert b"INVALID_STATUS_TRANSITION" in result.body

    @pytest.mark.anyio
    async def test_unhandled_conflict_returns_500(self) -> None:
        exc = RuntimeError("unexpected")
        result = await conflict_error_handler(_make_request("req-6"), exc)
        assert result.status_code == 500
        assert b"DATABASE_ERROR" in result.body


class TestValidationErrorHandler:
    @pytest.mark.anyio
    async def test_employee_inactive(self) -> None:
        exc = CaseFileEmployeeInactiveError(uuid4())
        result = await validation_error_handler(_make_request("req-1"), exc)
        assert result.status_code == 422
        assert b"EMPLOYEE_INACTIVE" in result.body

    @pytest.mark.anyio
    async def test_unhandled_validation_returns_500(self) -> None:
        exc = ValueError("unexpected")
        result = await validation_error_handler(_make_request("req-2"), exc)
        assert result.status_code == 500
        assert b"DATABASE_ERROR" in result.body


class TestGenericErrorHandler:
    @pytest.mark.anyio
    async def test_generic_error(self) -> None:
        exc = RuntimeError("something broke")
        result = await generic_error_handler(_make_request("req-1"), exc)
        assert result.status_code == 500
        assert b"DATABASE_ERROR" in result.body

    @pytest.mark.anyio
    async def test_request_id_present(self) -> None:
        exc = RuntimeError("something broke")
        result = await generic_error_handler(_make_request("req-2"), exc)
        assert b"req-2" in result.body
