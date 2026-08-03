"""Contract tests for template endpoints."""

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
class TestCreateTemplate:
    async def test_create_template_returns_201(self, client):
        response = await client.post(
            "/api/v1/templates",
            json={
                "name": f"Plantilla {uuid.uuid4().hex[:8]}",
                "document_type": "resolucion",
                "body_template": "Cuerpo {{employee.first_name}}",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["version"] == 1
        assert data["is_active"] is True
        assert data["document_type"] == "resolucion"

    async def test_create_template_missing_fields_returns_422(self, client):
        response = await client.post(
            "/api/v1/templates",
            json={"name": "Test"},
        )
        assert response.status_code == 422

    async def test_create_template_extra_fields_returns_422(self, client):
        response = await client.post(
            "/api/v1/templates",
            json={
                "name": f"Test {uuid.uuid4().hex[:8]}",
                "document_type": "resolucion",
                "body_template": "body",
                "extra_field": "not_allowed",
            },
        )
        assert response.status_code == 422


@pytest.mark.contract
class TestGetTemplate:
    async def test_get_template_not_found_returns_404(self, client):
        response = await client.get(f"/api/v1/templates/{uuid.uuid4()}")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "DOCUMENT_TEMPLATE_NOT_FOUND"

    async def test_get_template_invalid_uuid_returns_422(self, client):
        response = await client.get("/api/v1/templates/invalid-uuid")
        assert response.status_code == 422


@pytest.mark.contract
class TestListTemplates:
    async def test_list_templates_returns_paginated(self, client):
        response = await client.get("/api/v1/templates")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data


@pytest.mark.contract
class TestUpdateTemplate:
    async def test_update_template_not_found_returns_404(self, client):
        response = await client.patch(
            f"/api/v1/templates/{uuid.uuid4()}",
            json={"body_template": "new body"},
        )
        assert response.status_code == 404

    async def test_update_template_invalid_uuid_returns_422(self, client):
        response = await client.patch(
            "/api/v1/templates/invalid-uuid",
            json={"body_template": "new body"},
        )
        assert response.status_code == 422


@pytest.mark.contract
class TestDeactivateTemplate:
    async def test_deactivate_template_not_found_returns_404(self, client):
        response = await client.post(f"/api/v1/templates/{uuid.uuid4()}/deactivate")
        assert response.status_code == 404

    async def test_deactivate_template_invalid_uuid_returns_422(self, client):
        response = await client.post("/api/v1/templates/invalid-uuid/deactivate")
        assert response.status_code == 422
