"""Pruebas de integración de migraciones."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine


@pytest.mark.integration
class TestMigrationsIntegration:
    """Pruebas de integración de migraciones Alembic."""

    @pytest.mark.asyncio
    async def test_pgvector_extension_exists(self) -> None:
        """Verifica que la migración habilitó pgvector."""
        engine = create_engine()
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                )
                row = result.fetchone()
                assert row is not None, "La extensión vector no está habilitada"
        finally:
            await engine.dispose()
