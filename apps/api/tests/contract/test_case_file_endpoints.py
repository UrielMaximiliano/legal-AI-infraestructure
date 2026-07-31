"""Contract tests for case file endpoints - success paths."""

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


async def _create_employee(client) -> dict:
    """Helper to create an employee and return the response data."""
    response = await client.post(
        "/api/v1/employees/",
        json={
            "employee_number": f"LEG-{uuid.uuid4().hex[:8]}",
            "first_name": "Test",
            "last_name": "Employee",
            "document_type": "dni",
            "document_number": str(uuid.uuid4().int)[:8],
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.contract
class TestCaseFileCreateSuccess:
    """Contract tests for POST /api/v1/case-files success path."""

    async def test_create_case_file_returns_201(self, client):
        employee = await _create_employee(client)
        response = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "Expediente de Designación",
                "case_type": "designacion",
                "description": "Test description",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert "case_number" in data
        assert data["case_number"].startswith("CF-")
        assert data["employee_id"] == employee["id"]
        assert data["title"] == "Expediente de Designación"
        assert data["case_type"] == "designacion"
        assert data["status"] == "draft"
        assert data["version"] == 1
        assert "opened_at" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert data["closed_at"] is None

    async def test_create_case_file_employee_not_found_returns_404(self, client):
        response = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": str(uuid.uuid4()),
                "title": "Test",
                "case_type": "designacion",
            },
        )
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "EMPLOYEE_NOT_FOUND"

    async def test_create_case_file_inactive_employee_returns_422(self, client):
        employee = await _create_employee(client)
        # Deactivate employee
        await client.post(f"/api/v1/employees/{employee['id']}/deactivate")
        response = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "Test",
                "case_type": "designacion",
            },
        )
        assert response.status_code == 422
        data = response.json()
        assert data["error_code"] == "EMPLOYEE_INACTIVE"


@pytest.mark.contract
class TestCaseFileGetSuccess:
    """Contract tests for GET /api/v1/case-files/{id} success path."""

    async def test_get_case_file_returns_200(self, client):
        employee = await _create_employee(client)
        create_resp = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "Test Case",
                "case_type": "designacion",
            },
        )
        case_file_id = create_resp.json()["id"]

        response = await client.get(f"/api/v1/case-files/{case_file_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == case_file_id
        assert data["title"] == "Test Case"
        assert data["status"] == "draft"


@pytest.mark.contract
class TestCaseFileUpdateSuccess:
    """Contract tests for PATCH /api/v1/case-files/{id} success path."""

    async def test_update_case_file_returns_200(self, client):
        employee = await _create_employee(client)
        create_resp = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "Original Title",
                "case_type": "designacion",
            },
        )
        case_file = create_resp.json()

        response = await client.patch(
            f"/api/v1/case-files/{case_file['id']}",
            json={"title": "Updated Title", "expected_version": case_file["version"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["version"] == 2


@pytest.mark.contract
class TestCaseFileTransitionSuccess:
    """Contract tests for POST /api/v1/case-files/{id}/transitions success path."""

    async def test_transition_draft_to_under_review(self, client):
        employee = await _create_employee(client)
        create_resp = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "Transition Test",
                "case_type": "designacion",
            },
        )
        case_file = create_resp.json()

        response = await client.post(
            f"/api/v1/case-files/{case_file['id']}/transitions",
            json={
                "status": "under_review",
                "expected_version": case_file["version"],
                "changed_by": "test-user",
                "reason": "Starting review",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "under_review"
        assert data["version"] == 2


@pytest.mark.contract
class TestCaseFileHistorySuccess:
    """Contract tests for GET /api/v1/case-files/{id}/history success path."""

    async def test_get_history_returns_initial_entry(self, client):
        employee = await _create_employee(client)
        create_resp = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "History Test",
                "case_type": "designacion",
            },
        )
        case_file_id = create_resp.json()["id"]

        response = await client.get(f"/api/v1/case-files/{case_file_id}/history")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["to_status"] == "draft"
        assert item["changed_by"] == "system"
        assert item["from_status"] is None

    async def test_get_history_after_transition(self, client):
        employee = await _create_employee(client)
        create_resp = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "History Test",
                "case_type": "designacion",
            },
        )
        case_file = create_resp.json()

        # Perform transition
        await client.post(
            f"/api/v1/case-files/{case_file['id']}/transitions",
            json={
                "status": "under_review",
                "expected_version": case_file["version"],
                "changed_by": "test-user",
            },
        )

        response = await client.get(f"/api/v1/case-files/{case_file['id']}/history")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["items"][0]["to_status"] == "draft"
        assert data["items"][1]["to_status"] == "under_review"


@pytest.mark.contract
class TestCaseFileArchivedErrors:
    """Contract tests for errors when case file is archived."""

    async def test_update_archived_returns_409(self, client):
        employee = await _create_employee(client)
        create_resp = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "Archive Test",
                "case_type": "designacion",
            },
        )
        cf = create_resp.json()

        # Transition to under_review
        await client.post(
            f"/api/v1/case-files/{cf['id']}/transitions",
            json={
                "status": "under_review",
                "expected_version": cf["version"],
                "changed_by": "u",
            },
        )
        # Transition to in_process
        await client.post(
            f"/api/v1/case-files/{cf['id']}/transitions",
            json={"status": "in_process", "expected_version": 2, "changed_by": "u"},
        )
        # Transition to submitted
        await client.post(
            f"/api/v1/case-files/{cf['id']}/transitions",
            json={"status": "submitted", "expected_version": 3, "changed_by": "u"},
        )
        # Transition to approved
        await client.post(
            f"/api/v1/case-files/{cf['id']}/transitions",
            json={"status": "approved", "expected_version": 4, "changed_by": "u"},
        )
        # Transition to archived
        await client.post(
            f"/api/v1/case-files/{cf['id']}/transitions",
            json={"status": "archived", "expected_version": 5, "changed_by": "u"},
        )

        # Try to update archived
        response = await client.patch(
            f"/api/v1/case-files/{cf['id']}",
            json={"title": "Updated", "expected_version": 6},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "CASE_FILE_ARCHIVED"

    async def test_transition_archived_returns_409(self, client):
        employee = await _create_employee(client)
        create_resp = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "Archive Test",
                "case_type": "designacion",
            },
        )
        cf = create_resp.json()

        # Transition to under_review -> in_process -> submitted -> approved -> archived
        for i, status in enumerate(
            ["under_review", "in_process", "submitted", "approved", "archived"], 1
        ):
            await client.post(
                f"/api/v1/case-files/{cf['id']}/transitions",
                json={"status": status, "expected_version": i, "changed_by": "u"},
            )

        # Try to transition archived
        response = await client.post(
            f"/api/v1/case-files/{cf['id']}/transitions",
            json={"status": "draft", "expected_version": 6, "changed_by": "u"},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "CASE_FILE_ARCHIVED"


@pytest.mark.contract
class TestCaseFileConcurrentModification:
    """Contract tests for optimistic locking errors."""

    async def test_update_version_mismatch_returns_409(self, client):
        employee = await _create_employee(client)
        create_resp = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "Version Test",
                "case_type": "designacion",
            },
        )
        cf = create_resp.json()

        # Update with wrong version
        response = await client.patch(
            f"/api/v1/case-files/{cf['id']}",
            json={"title": "Updated", "expected_version": 999},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "CONCURRENT_MODIFICATION"

    async def test_transition_version_mismatch_returns_409(self, client):
        employee = await _create_employee(client)
        create_resp = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "Version Test",
                "case_type": "designacion",
            },
        )
        cf = create_resp.json()

        response = await client.post(
            f"/api/v1/case-files/{cf['id']}/transitions",
            json={"status": "under_review", "expected_version": 999, "changed_by": "u"},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "CONCURRENT_MODIFICATION"


@pytest.mark.contract
class TestCaseFileInvalidTransition:
    """Contract tests for invalid state transitions."""

    async def test_invalid_transition_returns_409(self, client):
        employee = await _create_employee(client)
        create_resp = await client.post(
            "/api/v1/case-files/",
            json={
                "employee_id": employee["id"],
                "title": "Invalid Transition",
                "case_type": "designacion",
            },
        )
        cf = create_resp.json()

        # Try to go from draft to approved (not allowed)
        response = await client.post(
            f"/api/v1/case-files/{cf['id']}/transitions",
            json={
                "status": "approved",
                "expected_version": cf["version"],
                "changed_by": "u",
            },
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "INVALID_STATUS_TRANSITION"
