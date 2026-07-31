"""Pruebas de integración con PostgreSQL real."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine


@pytest.mark.integration
class TestPostgresIntegration:
    """Pruebas de integración con PostgreSQL."""

    @pytest.mark.asyncio
    async def test_connection(self) -> None:
        """Verifica conexión a PostgreSQL."""
        engine = create_engine()
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_pgvector_extension(self) -> None:
        """Verifica que pgvector está habilitado."""
        engine = create_engine()
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                )
                row = result.fetchone()
                assert row is not None
                assert row[0] == "vector"
        finally:
            await engine.dispose()
