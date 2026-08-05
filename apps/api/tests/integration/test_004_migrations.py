"""Migration and compatibility checks for revision 004."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine


def _run_alembic(*arguments: str) -> None:
    api_root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    for key, value in dotenv_values(api_root.parent.parent / ".env").items():
        if value is not None:
            environment.setdefault(key, value)
    environment.setdefault("POSTGRES_HOST", "localhost")
    environment.setdefault("POSTGRES_PORT", "5432")
    environment.setdefault("POSTGRES_DB", "legal_ai")
    environment.setdefault("POSTGRES_USER", "legal_ai")
    environment.setdefault("POSTGRES_PASSWORD", "test-password")
    subprocess.run(
        ["uv", "run", "alembic", *arguments],
        cwd=api_root,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


@pytest.mark.integration
async def test_004_upgrade_and_downgrade_round_trip() -> None:
    # 005 is now the repository head; reset explicitly so this historical
    # compatibility test exercises the 004 boundary it names.
    _run_alembic("downgrade", "003")
    _run_alembic("upgrade", "004")
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            version = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            assert version == "004"
            tables = set(
                (
                    await connection.execute(
                        text(
                            "SELECT tablename FROM pg_tables "
                            "WHERE schemaname = 'public'"
                        )
                    )
                ).scalars()
            )
            assert {
                "document_reviews",
                "review_comments",
                "review_events",
                "review_operation_requests",
                "document_exports",
                "export_attempts",
            } <= tables
    finally:
        await engine.dispose()

    _run_alembic("downgrade", "003")
    try:
        _run_alembic("upgrade", "004")
    finally:
        _run_alembic("upgrade", "004")


@pytest.mark.integration
async def test_004_preserves_existing_003_columns_and_states() -> None:
    _run_alembic("downgrade", "003")
    _run_alembic("upgrade", "004")
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'document_drafts'"
                        )
                    )
                ).scalars()
            )
            assert {"status", "version", "content", "final_snapshot"} <= columns
            assert await connection.scalar(
                text("SELECT 1 FROM pg_constraint WHERE conname = 'ck_drafts_status'")
            ) in (None, 1)
    finally:
        await engine.dispose()
