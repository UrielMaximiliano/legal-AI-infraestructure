"""Contrato de /health/live."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.main import app


@pytest.mark.contract
class TestHealthLiveContract:
    """Pruebas contractuales para GET /health/live."""

    @pytest.mark.asyncio
    async def test_returns_200(self) -> None:
        """Verifica que retorna HTTP 200."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/live")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_schema(self) -> None:
        """Verifica el schema de la respuesta."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/live")
        data = response.json()
        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert "request_id" in data
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_request_id_in_header(self) -> None:
        """Verifica que request_id está en el header."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/live")
        assert "X-Request-ID" in response.headers

    @pytest.mark.asyncio
    async def test_custom_request_id(self) -> None:
        """Verifica aceptación de request_id personalizado."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/health/live", headers={"X-Request-ID": "custom-id-123"}
            )
        assert response.headers["X-Request-ID"] == "custom-id-123"
