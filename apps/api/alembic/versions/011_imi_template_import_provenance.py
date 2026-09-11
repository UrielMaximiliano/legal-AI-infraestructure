"""IMI template import provenance (non-destructive, safe on legacy DB).

Revision ID: 011
Revises: 010

The IMI Core schema (imi.*) is provisioned from
infra/database/imi-core/init/*.sql, not from this legacy chain. This
migration only adds new provenance columns and PUBLISHED-immutability
triggers when the imi tables already exist, and is a no-op otherwise. It
never drops tables/columns and never logs legal content.
"""

# SQL strings stay readable as adjacent literals; line length is not useful.
# ruff: noqa: E501

from collections.abc import Sequence

from alembic import op

revision = "011"
down_revision = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('imi.template_import_jobs') IS NOT NULL THEN
            ALTER TABLE imi.template_import_jobs
              ADD COLUMN IF NOT EXISTS source_sha256 char(64),
              ADD COLUMN IF NOT EXISTS source_size_bytes integer,
              ADD COLUMN IF NOT EXISTS extractor_version varchar(50),
              ADD COLUMN IF NOT EXISTS candidates_json jsonb NOT NULL DEFAULT '[]'::jsonb,
              ADD COLUMN IF NOT EXISTS decisions_json jsonb NOT NULL DEFAULT '[]'::jsonb,
              ADD COLUMN IF NOT EXISTS decided_by varchar(200),
              ADD COLUMN IF NOT EXISTS decided_at timestamptz;
          END IF;
          IF to_regclass('imi.template_version_configs') IS NOT NULL THEN
            ALTER TABLE imi.template_version_configs
              ADD COLUMN IF NOT EXISTS source_import_id uuid,
              ADD COLUMN IF NOT EXISTS source_sha256 char(64),
              ADD COLUMN IF NOT EXISTS extractor_version varchar(50);
          END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('imi.template_import_jobs') IS NOT NULL
             AND NOT EXISTS (
               SELECT 1 FROM pg_constraint
               WHERE conname = 'ck_template_import_jobs_source_sha'
             ) THEN
            ALTER TABLE imi.template_import_jobs
              ADD CONSTRAINT ck_template_import_jobs_source_sha
              CHECK (source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$');
          END IF;
          IF to_regclass('imi.template_version_configs') IS NOT NULL
             AND NOT EXISTS (
               SELECT 1 FROM pg_constraint
               WHERE conname = 'ck_template_version_configs_source_sha'
             ) THEN
            ALTER TABLE imi.template_version_configs
              ADD CONSTRAINT ck_template_version_configs_source_sha
              CHECK (source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$');
          END IF;
        END
        $$;
        """
    )
    # Immutability triggers are fully defined in
    # infra/database/imi-core/init/005_template_import_provenance.sql so fresh
    # core volumes get them at init. Only create the index here when safe.
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('imi.template_version_configs') IS NOT NULL THEN
            CREATE INDEX IF NOT EXISTS ix_template_version_configs_source_import
              ON imi.template_version_configs (source_import_id);
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Non-destructive: keep provenance columns and history intact.
    pass
