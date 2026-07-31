"""Contract tests for error response format."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.main import app


@pytest.fixture
async def client():
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.contract
class TestValidationErrorResponse:
    """Contract tests for VALIDATION_ERROR response format."""

    async def test_validation_error_format(self, client):
        response = await client.post(
            "/api/v1/employees/",
            json={},
        )
        assert response.status_code == 422
        data = response.json()
        assert data["error_code"] == "VALIDATION_ERROR"
        assert "message" in data
        assert "errors" in data
        assert isinstance(data["errors"], list)
        assert len(data["errors"]) > 0
        for error in data["errors"]:
            assert "field" in error
            assert "code" in error
            assert "message" in error

    async def test_validation_error_no_sensitive_data(self, client):
        response = await client.post(
            "/api/v1/employees/",
            json={},
        )
        assert response.status_code == 422
        data = response.json()
        # Ensure no sensitive data in error messages
        error_str = str(data)
        assert "password" not in error_str.lower()
        assert "secret" not in error_str.lower()
        assert "token" not in error_str.lower()


@pytest.mark.contract
class TestNotFoundResponse:
    """Contract tests for NOT_FOUND response format."""

    async def test_not_found_response_format(self, client):
        response = await client.get(f"/api/v1/employees/{uuid.uuid4()}")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "EMPLOYEE_NOT_FOUND"
        assert "message" in data


@pytest.mark.contract
class TestConflictResponse:
    """Contract tests for CONFLICT response format."""

    async def test_conflict_response_format(self, client):
        # Create first employee
        emp_num = f"LEG-{uuid.uuid4().hex[:8]}"
        doc_num = str(uuid.uuid4().int)[:8]
        await client.post(
            "/api/v1/employees/",
            json={
                "employee_number": emp_num,
                "first_name": "Test",
                "last_name": "User",
                "document_type": "dni",
                "document_number": doc_num,
            },
        )
        # Try to create duplicate with same employee number
        response = await client.post(
            "/api/v1/employees/",
            json={
                "employee_number": emp_num,
                "first_name": "Test2",
                "last_name": "User2",
                "document_type": "dni",
                "document_number": str(uuid.uuid4().int)[:8],
            },
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "EMPLOYEE_NUMBER_CONFLICT"
        assert "field" in data


@pytest.mark.contract
class TestDocumentConflictResponse:
    """Contract tests for EMPLOYEE_DOCUMENT_CONFLICT response format."""

    async def test_document_conflict_returns_409(self, client):
        doc_num = str(uuid.uuid4().int)[:8]
        await client.post(
            "/api/v1/employees/",
            json={
                "employee_number": f"LEG-{uuid.uuid4().hex[:8]}",
                "first_name": "First",
                "last_name": "User",
                "document_type": "dni",
                "document_number": doc_num,
            },
        )
        response = await client.post(
            "/api/v1/employees/",
            json={
                "employee_number": f"LEG-{uuid.uuid4().hex[:8]}",
                "first_name": "Second",
                "last_name": "User",
                "document_type": "dni",
                "document_number": doc_num,
            },
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "EMPLOYEE_DOCUMENT_CONFLICT"
        assert "field" in data
