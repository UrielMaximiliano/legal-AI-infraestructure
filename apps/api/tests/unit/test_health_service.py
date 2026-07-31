"""Pruebas del servicio de health checks con fakes."""

from __future__ import annotations

import pytest

from legal_ai.application.health_service import HealthService
from legal_ai.domain.health import DependencyHealth, HealthStatus
from legal_ai.ports.database_health import DatabaseHealthPort
from legal_ai.ports.ollama_health import OllamaHealthPort


class FakeDatabaseHealth(DatabaseHealthPort):
    """Fake para pruebas de PostgreSQL."""

    def __init__(self, health: DependencyHealth) -> None:
        self._health = health

    async def check(self) -> DependencyHealth:
        return self._health


class FakeOllamaHealth(OllamaHealthPort):
    """Fake para pruebas de Ollama."""

    def __init__(self, health: DependencyHealth) -> None:
        self._health = health

    async def check(self) -> DependencyHealth:
        return self._health


@pytest.mark.unit
class TestHealthService:
    """Pruebas para HealthService."""

    @pytest.mark.asyncio
    async def test_all_healthy(self) -> None:
        """Verifica estado cuando todas las dependencias están OK."""
        db_health = DependencyHealth(status=HealthStatus.OK, latency_ms=10.0)
        ollama_health = DependencyHealth(status=HealthStatus.OK, latency_ms=30.0)
        db = FakeDatabaseHealth(db_health)
        ollama = FakeOllamaHealth(ollama_health)
        service = HealthService(db, ollama)

        result = await service.check_all()

        assert result.postgres.status == HealthStatus.OK
        assert result.ollama.status == HealthStatus.OK
        assert service.compute_readiness(result) == "ready"
        assert service.compute_aggregate_status(result).value == "ok"

    @pytest.mark.asyncio
    async def test_postgres_unavailable(self) -> None:
        """Verifica estado cuando PostgreSQL no está disponible."""
        db = FakeDatabaseHealth(
            DependencyHealth(
                status=HealthStatus.UNAVAILABLE,
                error_code="POSTGRES_UNAVAILABLE",
                message="PostgreSQL no accesible",
            )
        )
        ollama = FakeOllamaHealth(DependencyHealth(status=HealthStatus.OK))
        service = HealthService(db, ollama)

        result = await service.check_all()

        assert result.postgres.status == HealthStatus.UNAVAILABLE
        assert service.compute_readiness(result) == "not_ready"
        assert service.compute_aggregate_status(result).value == "partial"

    @pytest.mark.asyncio
    async def test_ollama_unavailable(self) -> None:
        """Verifica estado cuando Ollama no está disponible."""
        db = FakeDatabaseHealth(DependencyHealth(status=HealthStatus.OK))
        ollama = FakeOllamaHealth(
            DependencyHealth(
                status=HealthStatus.UNAVAILABLE,
                error_code="OLLAMA_UNAVAILABLE",
                message="Ollama no accesible",
            )
        )
        service = HealthService(db, ollama)

        result = await service.check_all()

        assert result.ollama.status == HealthStatus.UNAVAILABLE
        assert service.compute_readiness(result) == "not_ready"

    @pytest.mark.asyncio
    async def test_pgvector_missing(self) -> None:
        """Verifica estado cuando pgvector no está instalado."""
        db = FakeDatabaseHealth(
            DependencyHealth(
                status=HealthStatus.MISSING,
                error_code="PGVECTOR_MISSING",
                message="Extensión pgvector no instalada",
            )
        )
        ollama = FakeOllamaHealth(DependencyHealth(status=HealthStatus.OK))
        service = HealthService(db, ollama)

        result = await service.check_all()

        assert result.pgvector.status == HealthStatus.MISCONFIGURED
        assert service.compute_readiness(result) == "not_ready"

    @pytest.mark.asyncio
    async def test_now_utc_format(self) -> None:
        """Verifica formato UTC ISO 8601."""
        timestamp = HealthService.now_utc()
        assert "T" in timestamp
        assert "+" in timestamp or "Z" in timestamp
