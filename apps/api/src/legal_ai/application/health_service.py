"""Servicio de orquestación de health checks."""

from __future__ import annotations

import datetime

from legal_ai.domain.health import (
    AggregateStatus,
    DependencyHealth,
    HealthCheckResult,
    HealthStatus,
)
from legal_ai.ports.database_health import DatabaseHealthPort
from legal_ai.ports.ollama_health import OllamaHealthPort


class HealthService:
    """Servicio que orquesta las verificaciones de dependencias."""

    def __init__(
        self,
        database_health: DatabaseHealthPort,
        ollama_health: OllamaHealthPort,
    ) -> None:
        self._database_health = database_health
        self._ollama_health = ollama_health

    async def check_all(self) -> HealthCheckResult:
        """Ejecuta todas las verificaciones de dependencias."""
        postgres = await self._database_health.check()
        pgvector = await self._check_pgvector(postgres)
        ollama = await self._ollama_health.check()

        return HealthCheckResult(
            postgres=postgres,
            pgvector=pgvector,
            ollama=ollama,
        )

    async def _check_pgvector(self, postgres: DependencyHealth) -> DependencyHealth:
        """Verifica pgvector solo si PostgreSQL está disponible."""
        if postgres.status != HealthStatus.OK:
            return DependencyHealth(
                status=HealthStatus.MISCONFIGURED,
                error_code="PGVECTOR_CHECK_FAILED",
                message="PostgreSQL no disponible para verificar pgvector",
            )
        return DependencyHealth(status=HealthStatus.OK)

    def compute_aggregate_status(self, result: HealthCheckResult) -> AggregateStatus:
        """Calcula el estado agregado del diagnóstico."""
        all_deps = [result.postgres, result.pgvector, result.ollama]
        if all(d.status == HealthStatus.OK for d in all_deps):
            return AggregateStatus.OK
        return AggregateStatus.PARTIAL

    def compute_readiness(self, result: HealthCheckResult) -> str:
        """Calcula el estado de readiness."""
        all_deps = [result.postgres, result.pgvector, result.ollama]
        if all(d.status == HealthStatus.OK for d in all_deps):
            return "ready"
        return "not_ready"

    @staticmethod
    def now_utc() -> str:
        """Retorna la fecha y hora actual en UTC ISO 8601."""
        return datetime.datetime.now(datetime.UTC).isoformat()
