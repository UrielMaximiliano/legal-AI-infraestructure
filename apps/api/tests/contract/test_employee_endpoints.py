"""Contract tests for employee endpoints."""

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
class TestCreateEmployee:
    """Contract tests for POST /api/v1/employees."""

    async def test_create_employee_returns_201(self, client):
        response = await client.post(
            "/api/v1/employees/",
            json={
                "employee_number": f"LEG-{uuid.uuid4().hex[:8]}",
                "first_name": "Ana",
                "last_name": "Pérez",
                "document_type": "dni",
                "document_number": str(uuid.uuid4().int)[:8],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert "employee_number" in data
        assert "first_name" in data
        assert "last_name" in data
        assert "document_type" in data
        assert "document_number" in data
        assert "active" in data
        assert data["active"] is True
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_employee_invalid_uuid_returns_422(self, client):
        response = await client.post(
            "/api/v1/employees/",
            json={
                "employee_number": f"LEG-{uuid.uuid4().hex[:8]}",
                "first_name": "Ana",
                "last_name": "Pérez",
                "document_type": "dni",
                "document_number": str(uuid.uuid4().int)[:8],
            },
        )
        assert response.status_code == 201


@pytest.mark.contract
class TestGetEmployee:
    """Contract tests for GET /api/v1/employees/{id}."""

    async def test_get_employee_not_found_returns_404(self, client):
        response = await client.get(f"/api/v1/employees/{uuid.uuid4()}")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "EMPLOYEE_NOT_FOUND"

    async def test_get_employee_invalid_uuid_returns_422(self, client):
        response = await client.get("/api/v1/employees/invalid-uuid")
        assert response.status_code == 422


@pytest.mark.contract
class TestListEmployees:
    """Contract tests for GET /api/v1/employees."""

    async def test_list_employees_returns_paginated(self, client):
        response = await client.get("/api/v1/employees/")
        assert response.status_code == 200
        data = response.json()
        assert "page" in data
        assert "page_size" in data
        assert "total" in data
        assert "items" in data
        assert isinstance(data["items"], list)


@pytest.mark.contract
class TestUpdateEmployee:
    """Contract tests for PATCH /api/v1/employees/{id}."""

    async def test_update_employee_not_found_returns_404(self, client):
        response = await client.patch(
            f"/api/v1/employees/{uuid.uuid4()}",
            json={"first_name": "Updated"},
        )
        assert response.status_code == 404

    async def test_update_employee_returns_200(self, client):
        create_resp = await client.post(
            "/api/v1/employees/",
            json={
                "employee_number": f"LEG-{uuid.uuid4().hex[:8]}",
                "first_name": "Original",
                "last_name": "Name",
                "document_type": "dni",
                "document_number": str(uuid.uuid4().int)[:8],
            },
        )
        emp_id = create_resp.json()["id"]
        response = await client.patch(
            f"/api/v1/employees/{emp_id}",
            json={"first_name": "Updated"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Updated"

    async def test_update_extra_fields_returns_422(self, client):
        create_resp = await client.post(
            "/api/v1/employees/",
            json={
                "employee_number": f"LEG-{uuid.uuid4().hex[:8]}",
                "first_name": "Test",
                "last_name": "User",
                "document_type": "dni",
                "document_number": str(uuid.uuid4().int)[:8],
            },
        )
        emp_id = create_resp.json()["id"]
        response = await client.patch(
            f"/api/v1/employees/{emp_id}",
            json={"first_name": "Updated", "employee_number": "HACK"},
        )
        assert response.status_code == 422


@pytest.mark.contract
class TestGetEmployeeSuccess:
    """Contract tests for GET /api/v1/employees/{id} success path."""

    async def test_get_employee_returns_200(self, client):
        create_resp = await client.post(
            "/api/v1/employees/",
            json={
                "employee_number": f"LEG-{uuid.uuid4().hex[:8]}",
                "first_name": "Retrieve",
                "last_name": "Me",
                "document_type": "dni",
                "document_number": str(uuid.uuid4().int)[:8],
            },
        )
        emp_id = create_resp.json()["id"]
        response = await client.get(f"/api/v1/employees/{emp_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == emp_id
        assert data["first_name"] == "Retrieve"


@pytest.mark.contract
class TestDeactivateEmployee:
    """Contract tests for POST /api/v1/employees/{id}/deactivate."""

    async def test_deactivate_employee_not_found_returns_404(self, client):
        response = await client.post(f"/api/v1/employees/{uuid.uuid4()}/deactivate")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "EMPLOYEE_NOT_FOUND"

    async def test_deactivate_idempotent(self, client):
        # Create employee
        emp_num = f"LEG-{uuid.uuid4().hex[:8]}"
        create_response = await client.post(
            "/api/v1/employees/",
            json={
                "employee_number": emp_num,
                "first_name": "Test",
                "last_name": "User",
                "document_type": "dni",
                "document_number": str(uuid.uuid4().int)[:8],
            },
        )
        assert create_response.status_code == 201
        emp_id = create_response.json()["id"]

        # Deactivate once
        response1 = await client.post(f"/api/v1/employees/{emp_id}/deactivate")
        assert response1.status_code == 200
        assert response1.json()["active"] is False

        # Deactivate again (idempotent)
        response2 = await client.post(f"/api/v1/employees/{emp_id}/deactivate")
        assert response2.status_code == 200
        assert response2.json()["active"] is False
