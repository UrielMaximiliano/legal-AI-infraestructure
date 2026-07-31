"""Contrato de /health/ready."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.main import app


@pytest.mark.contract
class TestHealthReadyContract:
    """Pruebas contractuales para GET /health/ready."""

    @pytest.mark.asyncio
    async def test_returns_valid_status(self) -> None:
        """Verifica que retorna HTTP 200 o 503."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/ready")
        assert response.status_code in (200, 503)

    @pytest.mark.asyncio
    async def test_response_schema(self) -> None:
        """Verifica el schema de la respuesta."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/ready")
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "request_id" in data
        assert data["status"] in ("ready", "not_ready")

    @pytest.mark.asyncio
    async def test_503_when_not_ready(self) -> None:
        """Verifica HTTP 503 cuando no está ready."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/ready")
        if response.status_code == 503:
            data = response.json()
            assert data["status"] == "not_ready"

    @pytest.mark.asyncio
    async def test_no_degraded(self) -> None:
        """Verifica que degraded no se emite en este incremento."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/ready")
        data = response.json()
        assert data["status"] != "degraded"
