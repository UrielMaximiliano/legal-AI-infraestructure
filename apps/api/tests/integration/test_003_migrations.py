"""Migration round-trip and schema checks for revision 003."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine

NEW_TABLES = {
    "document_templates",
    "designation_data",
    "document_drafts",
    "draft_transitions",
    "generation_attempts",
}
OLD_TABLES = {"employees", "case_files", "case_status_history"}
EXPECTED_INDEXES = {
    "ix_templates_document_type",
    "ix_templates_is_active",
    "ix_templates_name",
    "ix_designation_data_case_file_id",
    "ix_drafts_case_file_id",
    "ix_drafts_status",
    "ix_drafts_parent_draft_id",
    "ix_drafts_template_id",
    "ix_drafts_context_hash",
    "ix_draft_transitions_draft_id",
    "ix_generation_attempts_idempotency_key",
    "ix_generation_attempts_case_file_id",
    "ix_generation_attempts_status",
}


async def _schema_snapshot() -> tuple[set[str], set[str], set[str]]:
    engine = create_engine()
    try:
        async with engine.connect() as connection:
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
            indexes = set(
                (
                    await connection.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE schemaname = 'public'"
                        )
                    )
                ).scalars()
            )
            fks = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name || ':' || constraint_name "
                            "FROM information_schema.table_constraints "
                            "WHERE constraint_type = 'FOREIGN KEY' "
                            "AND table_schema = 'public'"
                        )
                    )
                ).scalars()
            )
            return tables, indexes, fks
    finally:
        await engine.dispose()


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
async def test_revision_003_round_trip_preserves_previous_schema() -> None:
    _run_alembic("upgrade", "head")
    before_tables, _, _ = await _schema_snapshot()
    assert before_tables >= NEW_TABLES
    assert before_tables >= OLD_TABLES

    try:
        _run_alembic("downgrade", "002")
        downgraded_tables, _, _ = await _schema_snapshot()
        assert NEW_TABLES.isdisjoint(downgraded_tables)
        assert downgraded_tables >= OLD_TABLES
    finally:
        _run_alembic("upgrade", "head")

    tables, indexes, fks = await _schema_snapshot()
    assert tables >= NEW_TABLES
    assert tables >= OLD_TABLES
    assert indexes >= EXPECTED_INDEXES
    assert any(item.startswith("designation_data:") for item in fks)
    assert any(item.startswith("document_drafts:") for item in fks)
    assert any(item.startswith("draft_transitions:") for item in fks)
    assert any(item.startswith("generation_attempts:") for item in fks)


@pytest.mark.integration
async def test_003_constraints_and_pgvector_are_intact() -> None:
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            extension = await connection.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
            assert extension.scalar_one_or_none() == 1
            unique_constraint = await connection.execute(
                text(
                    "SELECT 1 FROM pg_constraint "
                    "WHERE conname = 'uq_template_name_type_version'"
                )
            )
            assert unique_constraint.scalar_one_or_none() == 1
            designation_unique = await connection.execute(
                text(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE indexname LIKE '%designation_data_case_file_id%' "
                    "AND indexdef ILIKE '%UNIQUE%'"
                )
            )
            assert designation_unique.scalar_one_or_none() == 1
    finally:
        await engine.dispose()
