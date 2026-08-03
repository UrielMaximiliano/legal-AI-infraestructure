"""Contract tests for generation attempt endpoints."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.application.ollama_client import OllamaResponse
from legal_ai.main import app
from tests.contract.helpers_003 import seed_case_and_template


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.contract
class TestGetGenerationAttempt:
    async def test_get_generation_attempt_success(self, client, monkeypatch):
        async def fake_generate(self, prompt):
            return OllamaResponse(content="ok", model="test")

        monkeypatch.setattr(
            "legal_ai.application.ollama_client.OllamaClient.generate", fake_generate
        )
        case_file_id, template_id = await seed_case_and_template()
        generated = await client.post(
            "/api/v1/drafts/generate",
            json={"template_id": str(template_id), "case_file_id": str(case_file_id)},
        )
        assert generated.status_code == 201
        attempts = await client.get(
            f"/api/v1/case-files/{case_file_id}/generation-attempts"
        )
        assert attempts.status_code == 200
        attempt_id = attempts.json()[0]["id"]
        response = await client.get(f"/api/v1/generation-attempts/{attempt_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert "prompt_content" not in response.json()

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
