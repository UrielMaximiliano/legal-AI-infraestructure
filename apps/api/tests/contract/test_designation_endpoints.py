"""Contract tests for designation endpoints."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.domain.enums import CaseType
from legal_ai.main import app
from tests.contract.helpers_003 import seed_case_and_template


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.contract
class TestCreateDesignation:
    async def test_create_designation_success(self, client):
        case_file_id, _ = await seed_case_and_template(
            with_designation=False, case_type=CaseType.DESIGNACION
        )
        response = await client.post(
            f"/api/v1/case-files/{case_file_id}/designation",
            json={"position_name": "Director"},
        )
        assert response.status_code == 201
        assert response.json()["position_name"] == "Director"

    async def test_create_designation_missing_fields_returns_422(self, client):
        case_file_id, _ = await seed_case_and_template(with_designation=False)
        response = await client.post(
            f"/api/v1/case-files/{case_file_id}/designation", json={}
        )
        assert response.status_code == 422

    async def test_create_designation_duplicate_returns_409(self, client):
        case_file_id, _ = await seed_case_and_template()
        response = await client.post(
            f"/api/v1/case-files/{case_file_id}/designation",
            json={"position_name": "Otro"},
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "DESIGNATION_EXISTS"

    async def test_create_designation_incompatible_type_returns_409(self, client):
        case_file_id, _ = await seed_case_and_template(with_designation=False)
        response = await client.post(
            f"/api/v1/case-files/{case_file_id}/designation",
            json={"position_name": "Director"},
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "CASE_FILE_TYPE_INCOMPATIBLE"

    async def test_create_designation_case_file_not_found(self, client):
        response = await client.post(
            f"/api/v1/case-files/{uuid.uuid4()}/designation",
            json={"position_name": "Director"},
        )
        assert response.status_code == 404

    async def test_create_designation_invalid_uuid_returns_422(self, client):
        response = await client.post(
            "/api/v1/case-files/invalid-uuid/designation",
            json={"position_name": "Director"},
        )
        assert response.status_code == 422


@pytest.mark.contract
class TestGetDesignation:
    async def test_get_designation_success(self, client):
        case_file_id, _ = await seed_case_and_template()
        response = await client.get(f"/api/v1/case-files/{case_file_id}/designation")
        assert response.status_code == 200
        assert response.json()["position_name"] == "Director"

    async def test_get_designation_not_found_returns_404(self, client):
        response = await client.get(f"/api/v1/case-files/{uuid.uuid4()}/designation")
        assert response.status_code == 404

    async def test_get_designation_invalid_uuid_returns_422(self, client):
        response = await client.get("/api/v1/case-files/invalid-uuid/designation")
        assert response.status_code == 422


@pytest.mark.contract
class TestUpdateDesignation:
    async def test_update_designation_success(self, client):
        case_file_id, _ = await seed_case_and_template()
        response = await client.put(
            f"/api/v1/case-files/{case_file_id}/designation",
            json={"position_name": "Coordinador"},
        )
        assert response.status_code == 200
        assert response.json()["position_name"] == "Coordinador"

    async def test_update_designation_not_found_returns_404(self, client):
        response = await client.put(
            f"/api/v1/case-files/{uuid.uuid4()}/designation",
            json={"position_name": "Director"},
        )
        assert response.status_code == 404
