"""004 contract checks for sanitized health/readiness responses."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.main import app


@pytest.mark.contract
@pytest.mark.asyncio
async def test_readiness_contract_has_request_id_and_no_internal_storage() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/health/ready", headers={"X-Request-ID": "health-004"}
        )
    assert response.status_code in {200, 503}
    payload = response.json()
    assert payload["request_id"] == "health-004"
    assert payload["status"] in {"ready", "not_ready"}
    assert "storage_path" not in response.text
    assert "C:\\" not in response.text


@pytest.mark.contract
@pytest.mark.asyncio
async def test_dependency_health_has_sanitized_ollama_status() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/dependencies")
    assert response.status_code in {200, 500}
    payload = response.json()
    assert "request_id" in payload
    assert "Authorization" not in response.text
    assert "OLLAMA_API_TOKEN" not in response.text
    assert "storage_path" not in response.text
