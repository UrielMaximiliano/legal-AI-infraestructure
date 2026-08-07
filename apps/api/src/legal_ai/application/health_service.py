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
        semantic_retrieval = self._semantic_retrieval_health(
            postgres=postgres,
            pgvector=pgvector,
            ollama=ollama,
        )

        return HealthCheckResult(
            postgres=postgres,
            pgvector=pgvector,
            ollama=ollama,
            semantic_retrieval=semantic_retrieval,
        )

    @staticmethod
    def _semantic_retrieval_health(
        *,
        postgres: DependencyHealth,
        pgvector: DependencyHealth,
        ollama: DependencyHealth,
    ) -> DependencyHealth:
        """Derive the semantic capability without hiding its dependency cause.

        The legacy health checks remain available independently.  This derived
        capability is what ingestion and semantic search gate on, and it keeps
        the response explicit when the provider, vector extension, or database
        is unavailable.
        """
        if postgres.status != HealthStatus.OK:
            return DependencyHealth(
                status=postgres.status,
                latency_ms=postgres.latency_ms,
                error_code="SEMANTIC_RETRIEVAL_DATABASE_UNAVAILABLE",
                message="Base de datos no disponible para recuperación semántica",
            )
        if pgvector.status != HealthStatus.OK:
            return DependencyHealth(
                status=pgvector.status,
                latency_ms=pgvector.latency_ms,
                error_code="SEMANTIC_RETRIEVAL_VECTOR_UNAVAILABLE",
                message="Capacidad vectorial no disponible",
            )
        if ollama.status != HealthStatus.OK:
            return DependencyHealth(
                status=ollama.status,
                latency_ms=ollama.latency_ms,
                error_code=(
                    ollama.error_code or "SEMANTIC_RETRIEVAL_PROVIDER_UNAVAILABLE"
                ),
                message="Proveedor de embeddings no disponible",
            )
        return DependencyHealth(
            status=HealthStatus.OK,
            latency_ms=max(
                value
                for value in (
                    postgres.latency_ms,
                    pgvector.latency_ms,
                    ollama.latency_ms,
                )
                if value is not None
            )
            if any(
                value is not None
                for value in (
                    postgres.latency_ms,
                    pgvector.latency_ms,
                    ollama.latency_ms,
                )
            )
            else None,
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
        if result.semantic_retrieval is not None:
            all_deps.append(result.semantic_retrieval)
        if all(d.status == HealthStatus.OK for d in all_deps):
            return AggregateStatus.OK
        return AggregateStatus.PARTIAL

    def compute_readiness(self, result: HealthCheckResult) -> str:
        """Calcula el estado de readiness."""
        all_deps = [result.postgres, result.pgvector, result.ollama]
        if result.semantic_retrieval is not None:
            all_deps.append(result.semantic_retrieval)
        if all(d.status == HealthStatus.OK for d in all_deps):
            return "ready"
        return "not_ready"

    @staticmethod
    def now_utc() -> str:
        """Retorna la fecha y hora actual en UTC ISO 8601."""
        return datetime.datetime.now(datetime.UTC).isoformat()
