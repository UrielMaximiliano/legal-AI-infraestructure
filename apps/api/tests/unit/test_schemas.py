"""Unit tests for Pydantic schemas."""

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from legal_ai.domain.enums import CaseStatus
from legal_ai.schemas.case_file import (
    CaseFileResponse,
    CreateCaseFileRequest,
    HistoryItem,
    HistoryResponse,
    TransitionRequest,
    UpdateCaseFileRequest,
)
from legal_ai.schemas.employee import (
    CreateEmployeeRequest,
    EmployeeResponse,
    UpdateEmployeeRequest,
)
from legal_ai.schemas.errors import ErrorResponse, ValidationErrorDetail
from legal_ai.schemas.pagination import PaginatedResponse


class TestCreateEmployeeRequest:
    """Tests for CreateEmployeeRequest schema."""

    def test_valid_request(self):
        request = CreateEmployeeRequest(
            employee_number="LEG-001",
            first_name="Ana",
            last_name="Pérez",
            document_type="dni",
            document_number="30111222",
        )
        assert request.employee_number == "LEG-001"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            CreateEmployeeRequest(
                employee_number="LEG-001",
                first_name="Ana",
                last_name="Pérez",
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            CreateEmployeeRequest(
                employee_number="LEG-001",
                first_name="Ana",
                last_name="Pérez",
                document_type="dni",
                document_number="30111222",
                unknown_field="value",
            )


class TestUpdateEmployeeRequest:
    """Tests for UpdateEmployeeRequest schema."""

    def test_valid_request(self):
        request = UpdateEmployeeRequest(first_name="Ana")
        assert request.first_name == "Ana"

    def test_empty_request(self):
        request = UpdateEmployeeRequest()
        assert request.first_name is None

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            UpdateEmployeeRequest(unknown_field="value")


class TestCreateCaseFileRequest:
    """Tests for CreateCaseFileRequest schema."""

    def test_valid_request(self):
        request = CreateCaseFileRequest(
            employee_id=uuid.uuid4(),
            title="Test Case",
            case_type="designacion",
        )
        assert request.title == "Test Case"

    def test_invalid_case_type(self):
        with pytest.raises(ValidationError):
            CreateCaseFileRequest(
                employee_id=uuid.uuid4(),
                title="Test Case",
                case_type="invalid_type",
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            CreateCaseFileRequest(
                employee_id=uuid.uuid4(),
                title="Test Case",
                case_type="designacion",
                unknown_field="value",
            )


class TestUpdateCaseFileRequest:
    """Tests for UpdateCaseFileRequest schema."""

    def test_valid_request(self):
        request = UpdateCaseFileRequest(title="Updated", expected_version=1)
        assert request.title == "Updated"

    def test_missing_expected_version(self):
        with pytest.raises(ValidationError):
            UpdateCaseFileRequest(title="Updated")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            UpdateCaseFileRequest(
                title="Updated",
                expected_version=1,
                unknown_field="value",
            )


class TestTransitionRequest:
    """Tests for TransitionRequest schema."""

    def test_valid_request(self):
        request = TransitionRequest(
            status="under_review",
            expected_version=1,
            changed_by="user",
        )
        assert request.status == CaseStatus.UNDER_REVIEW

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            TransitionRequest(
                status="invalid_status",
                expected_version=1,
                changed_by="user",
            )

    def test_missing_changed_by(self):
        with pytest.raises(ValidationError):
            TransitionRequest(
                status="under_review",
                expected_version=1,
            )


class TestEmployeeResponse:
    """Tests for EmployeeResponse schema."""

    def test_valid_response(self):
        response = EmployeeResponse(
            id=uuid.uuid4(),
            employee_number="LEG-001",
            first_name="Ana",
            last_name="Pérez",
            document_type="dni",
            document_number="30111222",
            active=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert response.active is True


class TestCaseFileResponse:
    """Tests for CaseFileResponse schema."""

    def test_valid_response(self):
        response = CaseFileResponse(
            id=uuid.uuid4(),
            case_number="CF-123",
            employee_id=uuid.uuid4(),
            title="Test",
            case_type="designacion",
            status="draft",
            version=1,
            opened_at=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert response.version == 1


class TestHistoryResponse:
    """Tests for HistoryResponse schema."""

    def test_empty_history(self):
        response = HistoryResponse(items=[])
        assert len(response.items) == 0

    def test_with_items(self):
        item = HistoryItem(
            id=uuid.uuid4(),
            case_file_id=uuid.uuid4(),
            to_status="draft",
            changed_at=datetime.now(),
            changed_by="system",
        )
        response = HistoryResponse(items=[item])
        assert len(response.items) == 1


class TestPaginatedResponse:
    """Tests for PaginatedResponse schema."""

    def test_valid_response(self):
        response = PaginatedResponse(page=1, page_size=20, total=0, items=[])
        assert response.total == 0


class TestErrorResponse:
    """Tests for ErrorResponse schema."""

    def test_valid_error(self):
        error = ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="Invalid data",
        )
        assert error.error_code == "VALIDATION_ERROR"

    def test_with_errors(self):
        errors = [
            ValidationErrorDetail(field="name", code="required", message="Required")
        ]
        error = ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="Invalid data",
            errors=errors,
        )
        assert len(error.errors) == 1
