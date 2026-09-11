"""Safe schema bootstrap for IMI template provenance and immutable history.

The IMI Core database is created from ``infra/database/imi-core/init/*.sql``,
not from the legacy Alembic chain (which targets the historic legal-ai
database). This helper applies the same non-destructive DDL as
``005_template_import_provenance.sql`` so tests, CLIs and fresh volumes can
ensure the new columns and PUBLISHED-immutability triggers exist without
dropping or rewriting any table. It never logs legal content or PII.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_BOOTSTRAP_SQL_PATH = (
    Path(__file__).resolve().parents[6]
    / "infra"
    / "database"
    / "imi-core"
    / "init"
    / "005_template_import_provenance.sql"
)

# Discrete idempotent statements used by ensure_... (one execute per item,
# so asyncpg prepared statements never receive multiple commands at once).
_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE imi.template_import_jobs "
    "ADD COLUMN IF NOT EXISTS source_sha256 char(64)",
    "ALTER TABLE imi.template_import_jobs "
    "ADD COLUMN IF NOT EXISTS source_size_bytes integer",
    "ALTER TABLE imi.template_import_jobs "
    "ADD COLUMN IF NOT EXISTS extractor_version varchar(50)",
    "ALTER TABLE imi.template_import_jobs "
    "ADD COLUMN IF NOT EXISTS candidates_json jsonb NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE imi.template_import_jobs "
    "ADD COLUMN IF NOT EXISTS decisions_json jsonb NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE imi.template_import_jobs "
    "ADD COLUMN IF NOT EXISTS decided_by varchar(200)",
    "ALTER TABLE imi.template_import_jobs "
    "ADD COLUMN IF NOT EXISTS decided_at timestamptz",
    "ALTER TABLE imi.template_version_configs "
    "ADD COLUMN IF NOT EXISTS source_import_id uuid",
    "ALTER TABLE imi.template_version_configs "
    "ADD COLUMN IF NOT EXISTS source_sha256 char(64)",
    "ALTER TABLE imi.template_version_configs "
    "ADD COLUMN IF NOT EXISTS extractor_version varchar(50)",
    "CREATE INDEX IF NOT EXISTS ix_template_version_configs_source_import "
    "ON imi.template_version_configs (source_import_id)",
)


def bootstrap_sql() -> str:
    """Return the idempotent DDL text without executing it."""
    if _BOOTSTRAP_SQL_PATH.exists():
        return _BOOTSTRAP_SQL_PATH.read_text(encoding="utf-8")
    return ";\n".join(_STATEMENTS) + ";"


async def ensure_imi_template_provenance(session: AsyncSession) -> None:
    """Apply provenance columns and immutability guardrails if missing.

    Executes one idempotent statement at a time. Trigger/function bodies live
    in the 005 SQL init file and are applied by Postgres init volumes; this
    bootstrap guarantees the columns/indexes exist for existing volumes
    without destructive rewrites.
    """
    for statement in _STATEMENTS:
        await session.execute(text(statement))
