"""Contract tests for the optional private BFF service-token boundary."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.config import settings
from legal_ai.main import app


@pytest.mark.asyncio
async def test_api_routes_require_the_configured_bff_token(monkeypatch) -> None:
    monkeypatch.setattr(settings.service, "service_token", "service-secret")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get("/api/v1/drafts")
        invalid = await client.get(
            "/api/v1/drafts", headers={"Authorization": "Bearer wrong-secret"}
        )

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "SERVICE_AUTH_REQUIRED"
    assert invalid.status_code == 403
    assert invalid.json()["error_code"] == "SERVICE_AUTH_INVALID"


@pytest.mark.asyncio
async def test_health_routes_remain_available_for_orchestration(monkeypatch) -> None:
    monkeypatch.setattr(settings.service, "service_token", "service-secret")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
