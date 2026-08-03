"""003 templates, drafts and generation

Revision ID: 003
Revises: 002
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create document_templates table
    op.create_table(
        "document_templates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("organ_emisor", sa.String(200), nullable=True),
        sa.Column("normativa", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column(
            "variables", JSONB(), nullable=True, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "name", "document_type", "version", name="uq_template_name_type_version"
        ),
    )
    op.create_index(
        "ix_templates_document_type", "document_templates", ["document_type"]
    )
    op.create_index("ix_templates_is_active", "document_templates", ["is_active"])
    op.create_index("ix_templates_name", "document_templates", ["name"])

    # Create designation_data table
    op.create_table(
        "designation_data",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "case_file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("case_files.id"),
            unique=True,
            nullable=False,
        ),
        sa.Column("position_name", sa.String(200), nullable=False),
        sa.Column("organizational_unit", sa.String(200), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("legal_basis", sa.Text(), nullable=True),
        sa.Column("appointing_authority", sa.String(200), nullable=True),
        sa.Column("salary_category", sa.String(100), nullable=True),
        sa.Column("work_schedule", sa.String(100), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_designation_data_case_file_id", "designation_data", ["case_file_id"]
    )

    # Create document_drafts table
    op.create_table(
        "document_drafts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_templates.id"),
            nullable=False,
        ),
        sa.Column(
            "case_file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("case_files.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'generado'"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "generation_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("context_snapshot", JSONB(), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column(
            "variables_used",
            JSONB(),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "parent_draft_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_drafts.id"),
            nullable=True,
        ),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_drafts_case_file_id", "document_drafts", ["case_file_id"])
    op.create_index("ix_drafts_status", "document_drafts", ["status"])
    op.create_index("ix_drafts_parent_draft_id", "document_drafts", ["parent_draft_id"])
    op.create_index("ix_drafts_template_id", "document_drafts", ["template_id"])
    op.create_index("ix_drafts_context_hash", "document_drafts", ["context_hash"])

    # Create draft_transitions table
    op.create_table(
        "draft_transitions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "draft_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_drafts.id"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(20), nullable=False),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("performed_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_draft_transitions_draft_id", "draft_transitions", ["draft_id"])

    # Create generation_attempts table
    op.create_table(
        "generation_attempts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "case_file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("case_files.id"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_templates.id"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("prompt_content", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'in_progress'"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_generation_attempts_idempotency_key",
        "generation_attempts",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_generation_attempts_case_file_id",
        "generation_attempts",
        ["case_file_id"],
    )
    op.create_index("ix_generation_attempts_status", "generation_attempts", ["status"])


def downgrade() -> None:
    op.drop_table("generation_attempts")
    op.drop_table("draft_transitions")
    op.drop_table("document_drafts")
    op.drop_table("designation_data")
    op.drop_table("document_templates")
