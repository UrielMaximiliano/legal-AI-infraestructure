"""Regresión de health: una caída semántica no rompe la capability 001–004."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.api.routes import health as health_routes
from legal_ai.application.health_service import HealthService
from legal_ai.domain.health import DependencyHealth, HealthStatus
from legal_ai.main import app
from tests.unit.test_health_service import FakeDatabaseHealth, FakeOllamaHealth


@pytest.mark.contract
@pytest.mark.asyncio
async def test_liveness_and_legacy_readiness_survive_embedding_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = HealthService(
        FakeDatabaseHealth(DependencyHealth(status=HealthStatus.OK)),
        FakeOllamaHealth(
            DependencyHealth(
                status=HealthStatus.UNAVAILABLE,
                error_code="OLLAMA_UNAVAILABLE",
            )
        ),
    )
    monkeypatch.setattr(health_routes, "_get_health_service", lambda: service)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")
        dependencies = await client.get("/health/dependencies")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"
    payload = dependencies.json()
    assert payload["dependencies"]["semantic_retrieval"]["status"] == "unavailable"
    assert payload["dependencies"]["semantic_retrieval"]["error_code"] == (
        "OLLAMA_UNAVAILABLE"
    )
