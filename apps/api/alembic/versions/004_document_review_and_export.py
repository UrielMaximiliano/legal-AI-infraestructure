"""004 human review, finalization metadata and export metadata.

Revision ID: 004
Revises: 003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def _enum_check(column: str, values: tuple[str, ...], name: str) -> sa.CheckConstraint:
    quoted = ",".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({quoted})", name=name)


def upgrade() -> None:
    """Create 004 tables after extending the 003 draft table."""
    op.add_column(
        "document_drafts",
        sa.Column("finalized_by", sa.String(100), nullable=True),
    )
    op.add_column(
        "document_drafts",
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_drafts",
        sa.Column("finalization_notes", sa.Text(), nullable=True),
    )
    op.add_column(
        "document_drafts",
        sa.Column("final_snapshot", JSONB(), nullable=True),
    )
    op.add_column(
        "document_drafts",
        sa.Column("final_snapshot_sha256", sa.String(64), nullable=True),
    )
    op.create_check_constraint(
        "ck_drafts_finalized_by_length",
        "document_drafts",
        "finalized_by IS NULL OR char_length(btrim(finalized_by)) BETWEEN 1 AND 100",
    )
    op.create_check_constraint(
        "ck_drafts_finalization_notes_length",
        "document_drafts",
        "finalization_notes IS NULL OR char_length(finalization_notes) <= 2000",
    )
    op.create_check_constraint(
        "ck_drafts_final_snapshot_sha256",
        "document_drafts",
        "final_snapshot_sha256 IS NULL OR final_snapshot_sha256 ~ '^[0-9a-fA-F]{64}$'",
    )
    op.create_check_constraint(
        "ck_drafts_finalization_complete",
        "document_drafts",
        "(finalized_at IS NULL AND finalized_by IS NULL AND final_snapshot IS NULL "
        "AND final_snapshot_sha256 IS NULL) OR "
        "(finalized_at IS NOT NULL AND finalized_by IS NOT NULL "
        "AND final_snapshot IS NOT NULL AND final_snapshot_sha256 IS NOT NULL)",
    )

    # Create exports before reviews so the review FK can be added explicitly
    # after the review table exists.
    op.create_table(
        "document_exports",
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
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("review_id", UUID(as_uuid=True), nullable=False),
        sa.Column("export_version", sa.Integer(), nullable=False),
        sa.Column("parent_export_id", UUID(as_uuid=True), nullable=True),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'PENDING'")
        ),
        sa.Column("storage_path", sa.String(500), nullable=True),
        sa.Column("file_name", sa.String(120), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("source_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("renderer_name", sa.String(100), nullable=True),
        sa.Column("renderer_version", sa.String(100), nullable=True),
        sa.Column("exported_by", sa.String(100), nullable=False),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_export_id"],
            ["document_exports.id"],
            name="fk_exports_parent_export_id",
        ),
        sa.UniqueConstraint(
            "draft_id",
            "format",
            "export_version",
            name="uq_export_draft_format_version",
        ),
        _enum_check("format", ("DOCX", "PDF"), "ck_export_format"),
        _enum_check(
            "status",
            ("PENDING", "GENERATING", "GENERATED", "FAILED", "SUPERSEDED"),
            "ck_export_status",
        ),
        sa.CheckConstraint(
            "draft_version > 0 AND export_version > 0",
            name="ck_export_positive_versions",
        ),
        sa.CheckConstraint(
            "char_length(file_name) BETWEEN 1 AND 120",
            name="ck_export_file_name_length",
        ),
        sa.CheckConstraint(
            "storage_path IS NULL OR char_length(storage_path) <= 500",
            name="ck_export_storage_path_length",
        ),
        sa.CheckConstraint(
            "source_snapshot_sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_export_source_hash"
        ),
        sa.CheckConstraint(
            "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_export_content_hash",
        ),
    )

    op.create_table(
        "export_attempts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("export_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "draft_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_drafts.id"),
            nullable=False,
        ),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'PENDING'")
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("exported_by", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(
            ["export_id"], ["document_exports.id"], name="fk_export_attempts_export_id"
        ),
        sa.UniqueConstraint(
            "export_id", "attempt_number", name="uq_export_attempt_number"
        ),
        _enum_check("format", ("DOCX", "PDF"), "ck_export_attempt_format"),
        _enum_check(
            "status",
            ("PENDING", "PROCESSING", "SUCCEEDED", "FAILED"),
            "ck_export_attempt_status",
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 16 AND 100",
            name="ck_export_attempt_key_length",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-fA-F]{64}$'", name="ck_export_attempt_request_hash"
        ),
        sa.CheckConstraint(
            "attempt_number > 0", name="ck_export_attempt_positive_number"
        ),
    )

    op.create_table(
        "document_reviews",
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
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("review_snapshot", JSONB(), nullable=False),
        sa.Column("review_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column(
            "status", sa.String(24), nullable=False, server_default=sa.text("'OPEN'")
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("opened_by", sa.String(100), nullable=False),
        sa.Column("submitted_by", sa.String(100), nullable=True),
        sa.Column("decided_by", sa.String(100), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
            "draft_id", "draft_version", name="uq_review_draft_version"
        ),
        _enum_check(
            "status",
            ("OPEN", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "CLOSED"),
            "ck_review_status",
        ),
        sa.CheckConstraint(
            "draft_version > 0 AND version > 0", name="ck_review_positive_versions"
        ),
        sa.CheckConstraint(
            "char_length(btrim(opened_by)) BETWEEN 1 AND 100",
            name="ck_review_opened_by_length",
        ),
        sa.CheckConstraint(
            "review_snapshot_sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_review_snapshot_hash",
        ),
    )

    op.create_foreign_key(
        "fk_exports_review_id",
        "document_exports",
        "document_reviews",
        ["review_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "review_comments",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "review_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_reviews.id"),
            nullable=False,
        ),
        sa.Column(
            "parent_comment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("review_comments.id"),
            nullable=True,
        ),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'OPEN'")
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("anchor", JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
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
        sa.Column("resolved_by", sa.String(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        _enum_check(
            "severity",
            ("INFO", "SUGGESTION", "WARNING", "BLOCKING"),
            "ck_review_comment_severity",
        ),
        _enum_check(
            "status", ("OPEN", "RESOLVED", "DISMISSED"), "ck_review_comment_status"
        ),
        sa.CheckConstraint(
            "char_length(btrim(author)) BETWEEN 1 AND 100",
            name="ck_review_comment_author_length",
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 10000", name="ck_review_comment_body"
        ),
    )

    op.create_table(
        "review_operation_requests",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_payload", JSONB(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.UniqueConstraint(
            "operation",
            "resource_id",
            "idempotency_key",
            name="uq_review_operation_request",
        ),
        _enum_check(
            "status",
            ("PROCESSING", "SUCCEEDED", "FAILED"),
            "ck_review_operation_status",
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 16 AND 100",
            name="ck_review_operation_key_length",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-fA-F]{64}$'",
            name="ck_review_operation_request_hash",
        ),
    )

    op.create_table(
        "review_events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "review_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_reviews.id"),
            nullable=True,
        ),
        sa.Column(
            "draft_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_drafts.id"),
            nullable=True,
        ),
        sa.Column(
            "export_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_exports.id"),
            nullable=True,
        ),
        sa.Column(
            "attempt_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "export_attempts.id",
                name="fk_review_events_attempt_id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(100), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("draft_version", sa.Integer(), nullable=True),
        sa.Column(
            "summary", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index("ix_drafts_finalized_at", "document_drafts", ["finalized_at"])
    op.create_index("ix_reviews_draft_id", "document_reviews", ["draft_id"])
    op.create_index("ix_reviews_status", "document_reviews", ["status"])
    op.create_index("ix_review_comments_review_id", "review_comments", ["review_id"])
    op.create_index("ix_review_comments_status", "review_comments", ["status"])
    op.create_index(
        "ix_review_events_review_created",
        "review_events",
        ["review_id", "created_at", "id"],
    )
    op.create_index(
        "ix_review_events_resource_created",
        "review_events",
        ["resource_type", "resource_id", "created_at", "id"],
    )
    op.create_index(
        "ix_exports_draft_format_status",
        "document_exports",
        ["draft_id", "format", "status"],
    )
    op.create_index(
        "ix_exports_parent_export_id", "document_exports", ["parent_export_id"]
    )
    op.create_index(
        "ix_exports_draft_created", "document_exports", ["draft_id", "created_at", "id"]
    )
    op.create_index(
        "uq_exports_active_generation",
        "document_exports",
        ["draft_id", "format"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING','GENERATING')"),
    )
    op.create_index(
        "ix_export_attempts_draft_format_created",
        "export_attempts",
        ["draft_id", "format", "created_at", "id"],
    )
    op.create_index("ix_export_attempts_status", "export_attempts", ["status"])
    op.create_index(
        "ix_export_attempts_actor_key_created",
        "export_attempts",
        ["exported_by", "idempotency_key", "created_at"],
    )
    op.create_index(
        "uq_export_attempt_active_actor_key",
        "export_attempts",
        ["exported_by", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING','PROCESSING')"),
    )
    op.create_index(
        "uq_review_events_reconciliation_run",
        "review_events",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text(
            "event_type = 'RECONCILIATION_RUN' AND run_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    """Remove 004 in reverse dependency order; 001–003 remain untouched."""
    op.drop_index("uq_review_events_reconciliation_run", table_name="review_events")
    op.drop_index("uq_export_attempt_active_actor_key", table_name="export_attempts")
    op.drop_index("ix_export_attempts_actor_key_created", table_name="export_attempts")
    op.drop_index("ix_export_attempts_status", table_name="export_attempts")
    op.drop_index(
        "ix_export_attempts_draft_format_created", table_name="export_attempts"
    )
    op.drop_index("uq_exports_active_generation", table_name="document_exports")
    op.drop_index("ix_exports_draft_created", table_name="document_exports")
    op.drop_index("ix_exports_parent_export_id", table_name="document_exports")
    op.drop_index("ix_exports_draft_format_status", table_name="document_exports")
    op.drop_index("ix_review_events_resource_created", table_name="review_events")
    op.drop_index("ix_review_events_review_created", table_name="review_events")
    op.drop_index("ix_review_comments_status", table_name="review_comments")
    op.drop_index("ix_review_comments_review_id", table_name="review_comments")
    op.drop_index("ix_reviews_status", table_name="document_reviews")
    op.drop_index("ix_reviews_draft_id", table_name="document_reviews")
    op.drop_index("ix_drafts_finalized_at", table_name="document_drafts")
    op.drop_table("review_events")
    op.drop_table("review_operation_requests")
    op.drop_table("review_comments")
    op.drop_constraint("fk_exports_review_id", "document_exports", type_="foreignkey")
    op.drop_table("document_reviews")
    op.drop_table("export_attempts")
    op.drop_table("document_exports")
    op.drop_constraint(
        "ck_drafts_final_snapshot_sha256", "document_drafts", type_="check"
    )
    op.execute(
        "ALTER TABLE document_drafts DROP CONSTRAINT IF EXISTS "
        "ck_drafts_finalization_complete"
    )
    op.drop_constraint(
        "ck_drafts_finalization_notes_length", "document_drafts", type_="check"
    )
    op.drop_constraint(
        "ck_drafts_finalized_by_length", "document_drafts", type_="check"
    )
    op.drop_column("document_drafts", "final_snapshot_sha256")
    op.drop_column("document_drafts", "final_snapshot")
    op.drop_column("document_drafts", "finalization_notes")
    op.drop_column("document_drafts", "finalized_at")
    op.drop_column("document_drafts", "finalized_by")
