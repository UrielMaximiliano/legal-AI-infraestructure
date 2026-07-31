"""Contrato de /health/dependencies."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.main import app


@pytest.mark.contract
class TestHealthDependenciesContract:
    """Pruebas contractuales para GET /health/dependencies."""

    @pytest.mark.asyncio
    async def test_returns_200_or_500(self) -> None:
        """Verifica que retorna HTTP 200 o 500."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/dependencies")
        assert response.status_code in (200, 500)

    @pytest.mark.asyncio
    async def test_response_schema(self) -> None:
        """Verifica el schema de la respuesta."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/dependencies")
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "request_id" in data
        assert "dependencies" in data
        assert data["status"] in ("ok", "partial", "error")

    @pytest.mark.asyncio
    async def test_dependencies_structure(self) -> None:
        """Verifica la estructura de dependencies."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/dependencies")
        data = response.json()
        deps = data["dependencies"]
        assert "postgres" in deps
        assert "pgvector" in deps
        assert "ollama" in deps

    @pytest.mark.asyncio
    async def test_individual_dependency_schema(self) -> None:
        """Verifica el schema de cada dependencia individual."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/dependencies")
        data = response.json()
        for dep_name in ("postgres", "pgvector", "ollama"):
            dep = data["dependencies"][dep_name]
            assert "status" in dep
            assert dep["status"] in (
                "ok",
                "unavailable",
                "timeout",
                "misconfigured",
                "invalid_response",
                "missing",
                "unauthorized",
                "forbidden",
                "rate_limited",
            )

    @pytest.mark.asyncio
    async def test_request_id_in_header(self) -> None:
        """Verifica que request_id está en el header."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/dependencies")
        assert "X-Request-ID" in response.headers
