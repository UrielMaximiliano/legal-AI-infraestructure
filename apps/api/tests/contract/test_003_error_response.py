"""Contract tests for 003 error responses."""

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
class TestErrorCodes:
    async def test_template_not_found_404(self, client):
        response = await client.get(f"/api/v1/templates/{uuid.uuid4()}")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "DOCUMENT_TEMPLATE_NOT_FOUND"
        assert "request_id" in data

    async def test_draft_not_found_404(self, client):
        response = await client.get(f"/api/v1/drafts/{uuid.uuid4()}")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "DRAFT_NOT_FOUND"

    async def test_case_file_not_found_404(self, client):
        response = await client.get(f"/api/v1/case-files/{uuid.uuid4()}/drafts")
        assert response.status_code == 404

    async def test_validation_error_422(self, client):
        response = await client.get("/api/v1/templates/invalid-uuid")
        assert response.status_code == 422
        data = response.json()
        assert data["error_code"] == "VALIDATION_ERROR"

    async def test_no_secrets_in_error_response(self, client):
        response = await client.get(f"/api/v1/templates/{uuid.uuid4()}")
        data = response.json()
        error_str = str(data)
        assert "test-token" not in error_str
        assert "OLLAMA_API_TOKEN" not in error_str
        assert (
            "password" not in error_str.lower()
            or "password" in data.get("message", "").lower()
        )

    async def test_error_response_has_request_id(self, client):
        response = await client.get(f"/api/v1/templates/{uuid.uuid4()}")
        data = response.json()
        assert "request_id" in data
