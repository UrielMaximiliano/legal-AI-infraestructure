"""Adaptador de verificación de salud de PostgreSQL."""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from legal_ai.domain.health import DependencyHealth, HealthStatus
from legal_ai.ports.database_health import DatabaseHealthPort


class PostgreSQLHealthAdapter(DatabaseHealthPort):
    """Adaptador para verificación de salud de PostgreSQL y pgvector."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def check(self) -> DependencyHealth:
        """Verifica conectividad con PostgreSQL y presencia de pgvector."""
        try:
            start = time.monotonic()
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                pg_latency = (time.monotonic() - start) * 1000

                result = await conn.execute(
                    text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                )
                row = result.fetchone()
                if row is None:
                    return DependencyHealth(
                        status=HealthStatus.MISSING,
                        error_code="PGVECTOR_MISSING",
                        message="Extensión pgvector no instalada",
                    )
                return DependencyHealth(
                    status=HealthStatus.OK,
                    latency_ms=pg_latency,
                )
        except Exception as e:
            error_msg = str(e).lower()
            if "timeout" in error_msg:
                return DependencyHealth(
                    status=HealthStatus.TIMEOUT,
                    error_code="POSTGRES_UNAVAILABLE",
                    message="Timeout al conectar con PostgreSQL",
                )
            return DependencyHealth(
                status=HealthStatus.UNAVAILABLE,
                error_code="POSTGRES_UNAVAILABLE",
                message="PostgreSQL no accesible",
            )
