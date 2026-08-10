"""007 PostgreSQL migration evidence on an explicitly isolated database."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine

from .rag_postgres_support import run_alembic

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_006_007_round_trip_preserves_rag_schema() -> None:
    # A fresh isolated database has no Alembic revision yet. Bootstrap the
    # immutable baseline before exercising the 006 <-> 007 round-trip.
    run_alembic("upgrade", "006")
    run_alembic("downgrade", "006")
    run_alembic("upgrade", "007")
    run_alembic("downgrade", "006")
    run_alembic("upgrade", "007")
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            version = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            tables = set(
                await connection.scalars(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public'"
                    )
                )
            )
    finally:
        await engine.dispose()
    assert version == "007"
    assert {
        "rag_generation_runs",
        "rag_retrieved_sources",
        "rag_structured_drafts",
        "rag_evaluation_results",
    }.issubset(tables)
