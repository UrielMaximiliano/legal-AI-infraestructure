"""Contract tests for designation endpoints."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.contract
class TestCreateDesignation:
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
    async def test_get_designation_not_found_returns_404(self, client):
        response = await client.get(f"/api/v1/case-files/{uuid.uuid4()}/designation")
        assert response.status_code == 404

    async def test_get_designation_invalid_uuid_returns_422(self, client):
        response = await client.get("/api/v1/case-files/invalid-uuid/designation")
        assert response.status_code == 422


@pytest.mark.contract
class TestUpdateDesignation:
    async def test_update_designation_not_found_returns_404(self, client):
        response = await client.put(
            f"/api/v1/case-files/{uuid.uuid4()}/designation",
            json={"position_name": "Director"},
        )
        assert response.status_code == 404
