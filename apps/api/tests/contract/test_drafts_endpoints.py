"""Contract tests for draft endpoints."""

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
class TestGenerateDraft:
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
