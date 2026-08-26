"""Align drafts with structured editing and official final numbering."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "008"
down_revision = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_drafts", sa.Column("document_type", sa.String(50), nullable=True)
    )
    op.add_column(
        "document_drafts",
        sa.Column("document_json", JSONB(none_as_null=True), nullable=True),
    )
    op.add_column(
        "document_drafts", sa.Column("idempotency_key", sa.String(128), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE document_drafts d SET document_type = "
            "COALESCE(t.document_type, 'otros') "
            "FROM document_templates t WHERE d.template_id = t.id"
        )
    )
    op.execute(
        sa.text(
            "UPDATE document_drafts SET document_type = 'otros' "
            "WHERE document_type IS NULL"
        )
    )
    op.alter_column("document_drafts", "document_type", nullable=False)
    op.create_index("ix_drafts_document_type", "document_drafts", ["document_type"])
    op.create_index(
        "uq_drafts_idempotency_key",
        "document_drafts",
        ["idempotency_key"],
        unique=True,
    )
    op.create_table(
        "draft_document_versions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "draft_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", JSONB(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("edited_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("draft_id", "version", name="uq_draft_document_version"),
        sa.CheckConstraint("version > 0", name="ck_draft_document_version_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(document) = 'object'",
            name="ck_draft_document_json_object",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_draft_document_content_sha256",
        ),
        sa.CheckConstraint(
            "source IN ('AI_GENERATED','MANUAL','HUMAN_EDIT')",
            name="ck_draft_document_source",
        ),
    )
    op.create_index(
        "ix_draft_document_versions_draft",
        "draft_document_versions",
        ["draft_id", "version"],
    )
    op.create_table(
        "official_document_identifiers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "draft_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_drafts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(24), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("draft_id", name="uq_official_document_draft"),
        sa.UniqueConstraint(
            "document_type", "number", "year", name="uq_official_document_identifier"
        ),
        sa.CheckConstraint("number > 0", name="ck_official_document_number_positive"),
        sa.CheckConstraint(
            "year BETWEEN 1900 AND 2200", name="ck_official_document_year"
        ),
    )
    op.create_index(
        "ix_official_document_identifiers_year",
        "official_document_identifiers",
        ["year"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_official_document_identifiers_year",
        table_name="official_document_identifiers",
    )
    op.drop_table("official_document_identifiers")
    op.drop_index(
        "ix_draft_document_versions_draft", table_name="draft_document_versions"
    )
    op.drop_table("draft_document_versions")
    op.drop_index("uq_drafts_idempotency_key", table_name="document_drafts")
    op.drop_index("ix_drafts_document_type", table_name="document_drafts")
    op.drop_column("document_drafts", "idempotency_key")
    op.drop_column("document_drafts", "document_json")
    op.drop_column("document_drafts", "document_type")
