"""Contract tests for draft endpoints."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.application.ollama_client import OllamaResponse, OllamaUnavailableError
from legal_ai.main import app
from tests.contract.helpers_003 import seed_case_and_template


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.contract
class TestGenerateDraft:
    async def test_full_draft_lifecycle_and_idempotency(self, client, monkeypatch):
        async def fake_generate(self, prompt):
            return OllamaResponse(content=f"generado: {prompt[:12]}", model="test")

        monkeypatch.setattr(
            "legal_ai.application.ollama_client.OllamaClient.generate", fake_generate
        )
        case_file_id, template_id = await seed_case_and_template()
        payload = {"template_id": str(template_id), "case_file_id": str(case_file_id)}
        key = f"contract-{uuid.uuid4().hex}"

        created = await client.post(
            "/api/v1/drafts/generate", json=payload, headers={"Idempotency-Key": key}
        )
        assert created.status_code == 201
        draft = created.json()
        cached = await client.post(
            "/api/v1/drafts/generate", json=payload, headers={"Idempotency-Key": key}
        )
        assert cached.status_code == 200
        assert cached.json()["id"] == draft["id"]

        listed = await client.get(f"/api/v1/case-files/{case_file_id}/drafts")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        fetched = await client.get(f"/api/v1/drafts/{draft['id']}")
        assert fetched.status_code == 200

        review = await client.post(
            f"/api/v1/drafts/{draft['id']}/transitions",
            json={"action": "send_to_review", "expected_version": 1},
        )
        assert review.status_code == 200
        edited = await client.patch(
            f"/api/v1/drafts/{draft['id']}/content",
            json={"content": "editado", "expected_version": 2},
        )
        assert edited.status_code == 200
        rejected = await client.post(
            f"/api/v1/drafts/{draft['id']}/transitions",
            json={"action": "reject", "expected_version": 3},
        )
        assert rejected.status_code == 200
        regenerated = await client.post(
            f"/api/v1/drafts/{draft['id']}/regenerate",
            json={"expected_version": 4},
        )
        assert regenerated.status_code == 201
        assert regenerated.json()["parent_draft_id"] == draft["id"]
        history = await client.get(f"/api/v1/drafts/{draft['id']}/history")
        assert history.status_code == 200
        assert len(history.json()) >= 4

    async def test_generation_error_persists_failed_attempt_without_draft(
        self, client, monkeypatch
    ):
        async def unavailable(self, prompt):
            raise OllamaUnavailableError()

        monkeypatch.setattr(
            "legal_ai.application.ollama_client.OllamaClient.generate", unavailable
        )
        case_file_id, template_id = await seed_case_and_template()
        response = await client.post(
            "/api/v1/drafts/generate",
            json={"template_id": str(template_id), "case_file_id": str(case_file_id)},
            headers={"Idempotency-Key": f"failed-{uuid.uuid4().hex}"},
        )
        assert response.status_code == 503
        attempts = await client.get(
            f"/api/v1/case-files/{case_file_id}/generation-attempts"
        )
        assert attempts.status_code == 200
        assert attempts.json()[0]["status"] == "failed"

    async def test_generation_payload_mismatch_returns_409(self, client, monkeypatch):
        async def fake_generate(self, prompt):
            return OllamaResponse(content="ok", model="test")

        monkeypatch.setattr(
            "legal_ai.application.ollama_client.OllamaClient.generate", fake_generate
        )
        case_file_id, template_id = await seed_case_and_template()
        key = f"mismatch-{uuid.uuid4().hex}"
        first = await client.post(
            "/api/v1/drafts/generate",
            json={"template_id": str(template_id), "case_file_id": str(case_file_id)},
            headers={"Idempotency-Key": key},
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/v1/drafts/generate",
            json={
                "template_id": str(template_id),
                "case_file_id": str(case_file_id),
                "variables": {"different": "payload"},
            },
            headers={"Idempotency-Key": key},
        )
        assert second.status_code == 409
        assert second.json()["error_code"] == "IDEMPOTENCY_KEY_MISMATCH"

    async def test_generate_draft_missing_fields_returns_422(self, client):
        response = await client.post(
            "/api/v1/drafts/generate",
            json={},
        )
        assert response.status_code == 422

    async def test_generate_draft_template_not_found(self, client):
        response = await client.post(
            "/api/v1/drafts/generate",
            json={
                "template_id": str(uuid.uuid4()),
                "case_file_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 404

    async def test_generate_draft_with_idempotency_key(self, client):
        response = await client.post(
            "/api/v1/drafts/generate",
            json={
                "template_id": str(uuid.uuid4()),
                "case_file_id": str(uuid.uuid4()),
            },
            headers={"Idempotency-Key": f"key-{uuid.uuid4().hex[:8]}"},
        )
        assert response.status_code == 404


@pytest.mark.contract
class TestListDrafts:
    async def test_list_drafts_invalid_uuid_returns_422(self, client):
        response = await client.get("/api/v1/case-files/invalid-uuid/drafts")
        assert response.status_code == 422

    async def test_list_drafts_not_found_returns_404(self, client):
        response = await client.get(f"/api/v1/case-files/{uuid.uuid4()}/drafts")
        assert response.status_code == 404

    async def test_list_drafts_supports_status_filter(self, client, monkeypatch):
        async def fake_generate(self, prompt):
            return OllamaResponse(content="ok", model="test")

        monkeypatch.setattr(
            "legal_ai.application.ollama_client.OllamaClient.generate", fake_generate
        )
        case_file_id, template_id = await seed_case_and_template()
        created = await client.post(
            "/api/v1/drafts/generate",
            json={"template_id": str(template_id), "case_file_id": str(case_file_id)},
        )
        assert created.status_code == 201
        filtered = await client.get(
            f"/api/v1/case-files/{case_file_id}/drafts?status=generado"
        )
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1


@pytest.mark.contract
class TestGetDraft:
    async def test_get_draft_not_found_returns_404(self, client):
        response = await client.get(f"/api/v1/drafts/{uuid.uuid4()}")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "DRAFT_NOT_FOUND"

    async def test_get_draft_invalid_uuid_returns_422(self, client):
        response = await client.get("/api/v1/drafts/invalid-uuid")
        assert response.status_code == 422


@pytest.mark.contract
class TestEditDraftContent:
    async def test_edit_draft_not_found_returns_404(self, client):
        response = await client.patch(
            f"/api/v1/drafts/{uuid.uuid4()}/content",
            json={"content": "new content", "expected_version": 1},
        )
        assert response.status_code == 404

    async def test_edit_invalid_version_returns_409(self, client, monkeypatch):
        async def fake_generate(self, prompt):
            return OllamaResponse(content="ok", model="test")

        monkeypatch.setattr(
            "legal_ai.application.ollama_client.OllamaClient.generate", fake_generate
        )
        case_file_id, template_id = await seed_case_and_template()
        created = await client.post(
            "/api/v1/drafts/generate",
            json={"template_id": str(template_id), "case_file_id": str(case_file_id)},
        )
        response = await client.patch(
            f"/api/v1/drafts/{created.json()['id']}/content",
            json={"content": "x", "expected_version": 99},
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "CONCURRENT_MODIFICATION"


@pytest.mark.contract
class TestTransitionDraft:
    async def test_transition_draft_not_found_returns_404(self, client):
        response = await client.post(
            f"/api/v1/drafts/{uuid.uuid4()}/transitions",
            json={
                "action": "send_to_review",
                "expected_version": 1,
            },
        )
        assert response.status_code == 404

    async def test_invalid_transition_returns_409(self, client, monkeypatch):
        async def fake_generate(self, prompt):
            return OllamaResponse(content="ok", model="test")

        monkeypatch.setattr(
            "legal_ai.application.ollama_client.OllamaClient.generate", fake_generate
        )
        case_file_id, template_id = await seed_case_and_template()
        created = await client.post(
            "/api/v1/drafts/generate",
            json={"template_id": str(template_id), "case_file_id": str(case_file_id)},
        )
        response = await client.post(
            f"/api/v1/drafts/{created.json()['id']}/transitions",
            json={"action": "approve", "expected_version": 1},
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "INVALID_DRAFT_TRANSITION"


@pytest.mark.contract
class TestRegenerateDraft:
    async def test_regenerate_draft_not_found_returns_404(self, client):
        response = await client.post(
            f"/api/v1/drafts/{uuid.uuid4()}/regenerate",
            json={"expected_version": 1},
        )
        assert response.status_code == 404


@pytest.mark.contract
class TestGetDraftHistory:
    async def test_get_draft_history_not_found_returns_404(self, client):
        response = await client.get(f"/api/v1/drafts/{uuid.uuid4()}/history")
        assert response.status_code == 404
