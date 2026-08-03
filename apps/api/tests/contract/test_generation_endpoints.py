"""Contract tests for generation attempt endpoints."""

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
class TestGetGenerationAttempt:
    async def test_get_attempt_not_found_returns_404(self, client):
        response = await client.get(f"/api/v1/generation-attempts/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_get_attempt_invalid_uuid_returns_422(self, client):
        response = await client.get("/api/v1/generation-attempts/invalid-uuid")
        assert response.status_code == 422


@pytest.mark.contract
class TestListGenerationAttempts:
    async def test_list_attempts_invalid_uuid_returns_422(self, client):
        response = await client.get(
            "/api/v1/case-files/invalid-uuid/generation-attempts"
        )
        assert response.status_code == 422

    async def test_list_attempts_returns_list(self, client):
        response = await client.get(
            f"/api/v1/case-files/{uuid.uuid4()}/generation-attempts"
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
