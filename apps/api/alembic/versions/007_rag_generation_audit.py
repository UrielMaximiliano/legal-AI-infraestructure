"""Add auditable RAG generation, source and evaluation persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "007"
down_revision = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_generation_runs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "generation_attempt_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "generation_attempts.id",
                name="fk_rag_runs_generation_attempt_id_generation_attempts",
                ondelete="SET NULL",
            ),
        ),
        sa.Column(
            "draft_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "document_drafts.id",
                name="fk_rag_runs_draft_id_document_drafts",
                ondelete="SET NULL",
            ),
        ),
        sa.Column(
            "case_file_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "case_files.id",
                name="fk_rag_runs_case_file_id_case_files",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "document_templates.id",
                name="fk_rag_runs_template_id_document_templates",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key_hash", sa.String(64)),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("context_hash", sa.String(64)),
        sa.Column("prompt_hash", sa.String(64)),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("generation_model", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("candidate_pool_size", sa.Integer(), nullable=False),
        sa.Column("minimum_score", sa.Numeric(6, 5)),
        sa.Column("retrieved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "context_tokens_estimate", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "schema_repair_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("retrieval_duration_ms", sa.Integer()),
        sa.Column("generation_duration_ms", sa.Integer()),
        sa.Column("validation_duration_ms", sa.Integer()),
        sa.Column("total_duration_ms", sa.Integer()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ("
            "'PENDING','RETRIEVING','GENERATING','VALIDATING','SUCCEEDED','FAILED'"
            ")",
            name="ck_rag_generation_runs_status",
        ),
        sa.CheckConstraint(
            "embedding_dimensions = 2560", name="ck_rag_runs_dimensions"
        ),
        sa.CheckConstraint(
            "embedding_model = 'qwen3-embedding:4b-q4_K_M'",
            name="ck_rag_runs_embedding_model",
        ),
        sa.CheckConstraint(
            "generation_model = 'qwen3.6:35b'", name="ck_rag_runs_generation_model"
        ),
        sa.CheckConstraint("schema_version > 0", name="ck_rag_runs_schema_version"),
        sa.CheckConstraint(
            "btrim(embedding_model) <> '' AND btrim(generation_model) <> '' AND "
            "btrim(prompt_version) <> ''",
            name="ck_rag_runs_metadata_nonempty",
        ),
        sa.CheckConstraint(
            "top_k BETWEEN 3 AND 20 AND candidate_pool_size BETWEEN top_k AND 50",
            name="ck_rag_runs_retrieval_limits",
        ),
        sa.CheckConstraint(
            "minimum_score IS NULL OR (minimum_score >= 0 AND minimum_score <= 1)",
            name="ck_rag_runs_score",
        ),
        sa.CheckConstraint(
            "retrieved_count >= 0 AND selected_count >= 0 AND "
            "selected_count <= retrieved_count AND context_bytes >= 0 AND "
            "context_tokens_estimate >= 0",
            name="ck_rag_runs_counts",
        ),
        sa.CheckConstraint(
            "schema_repair_count BETWEEN 0 AND 1", name="ck_rag_runs_repair_count"
        ),
        sa.CheckConstraint(
            "(retrieval_duration_ms IS NULL OR retrieval_duration_ms >= 0) AND "
            "(generation_duration_ms IS NULL OR generation_duration_ms >= 0) AND "
            "(validation_duration_ms IS NULL OR validation_duration_ms >= 0) AND "
            "(total_duration_ms IS NULL OR total_duration_ms >= 0)",
            name="ck_rag_runs_durations",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$' AND query_hash ~ '^[0-9a-f]{64}$' "
            "AND (idempotency_key_hash IS NULL OR "
            "idempotency_key_hash ~ '^[0-9a-f]{64}$')",
            name="ck_rag_runs_hashes",
        ),
        sa.CheckConstraint(
            "(status = 'SUCCEEDED' AND draft_id IS NOT NULL "
            "AND context_hash IS NOT NULL AND prompt_hash IS NOT NULL "
            "AND finished_at IS NOT NULL AND selected_count > 0 "
            "AND error_code IS NULL) OR "
            "(status = 'FAILED' AND finished_at IS NOT NULL "
            "AND error_code IS NOT NULL AND btrim(error_code) <> '' "
            "AND draft_id IS NULL) OR "
            "(status NOT IN ('SUCCEEDED','FAILED') AND finished_at IS NULL "
            "AND draft_id IS NULL)",
            name="ck_rag_runs_terminal_state",
        ),
        sa.CheckConstraint("btrim(request_id) <> ''", name="ck_rag_runs_request_id"),
    )
    op.create_index(
        "ix_rag_runs_case_created",
        "rag_generation_runs",
        ["case_file_id", "created_at"],
    )
    op.create_index(
        "ix_rag_runs_status_created", "rag_generation_runs", ["status", "created_at"]
    )
    op.create_index("ix_rag_runs_request_id", "rag_generation_runs", ["request_id"])
    op.create_index(
        "uq_rag_runs_idempotency_active",
        "rag_generation_runs",
        ["idempotency_key_hash"],
        unique=True,
        postgresql_where=sa.text(
            "idempotency_key_hash IS NOT NULL AND status <> 'FAILED'"
        ),
    )

    op.create_table(
        "rag_retrieved_sources",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "rag_generation_runs.id",
                name="fk_rag_sources_run_id_rag_runs",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "corpus_documents.id",
                name="fk_rag_sources_document_id_corpus_documents",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "corpus_chunks.id",
                name="fk_rag_sources_chunk_id_corpus_chunks",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("citation_id", sa.String(32), nullable=False),
        sa.Column("retrieval_rank", sa.Integer(), nullable=False),
        sa.Column("context_rank", sa.Integer()),
        sa.Column("similarity_score", sa.Numeric(8, 7), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("section_type", sa.String(40), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("run_id", "chunk_id", name="uq_rag_sources_run_chunk"),
        sa.UniqueConstraint(
            "run_id", "retrieval_rank", name="uq_rag_sources_run_retrieval_rank"
        ),
        sa.UniqueConstraint(
            "run_id", "citation_id", name="uq_rag_sources_run_citation"
        ),
        sa.CheckConstraint("retrieval_rank > 0", name="ck_rag_sources_retrieval_rank"),
        sa.CheckConstraint(
            "context_rank IS NULL OR context_rank > 0",
            name="ck_rag_sources_context_rank",
        ),
        sa.CheckConstraint(
            "similarity_score BETWEEN 0 AND 1", name="ck_rag_sources_score"
        ),
        sa.CheckConstraint("generation > 0", name="ck_rag_sources_generation"),
        sa.CheckConstraint(
            "btrim(section_type) <> ''", name="ck_rag_sources_section"
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_rag_sources_content_hash"
        ),
        sa.CheckConstraint(
            "disposition IN ("
            "'SELECTED','EXCLUDED_BUDGET','EXCLUDED_DIVERSITY','EXCLUDED_SCORE'"
            ")",
            name="ck_rag_sources_disposition",
        ),
        sa.CheckConstraint(
            "(disposition = 'SELECTED' AND context_rank IS NOT NULL) OR "
            "(disposition <> 'SELECTED' AND context_rank IS NULL)",
            name="ck_rag_sources_context_disposition",
        ),
    )
    op.create_index(
        "uq_rag_sources_run_context_rank",
        "rag_retrieved_sources",
        ["run_id", "context_rank"],
        unique=True,
        postgresql_where=sa.text("context_rank IS NOT NULL"),
    )

    op.create_table(
        "rag_structured_drafts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "rag_generation_runs.id",
                name="fk_rag_structured_drafts_run_id_rag_runs",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "document_drafts.id",
                name="fk_rag_structured_drafts_draft_id_document_drafts",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_json", JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("run_id", name="uq_rag_structured_drafts_run"),
        sa.UniqueConstraint("draft_id", name="uq_rag_structured_drafts_draft"),
        sa.CheckConstraint(
            "schema_version > 0", name="ck_rag_structured_drafts_schema_version"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content_json) = 'object'",
            name="ck_rag_structured_drafts_json_object",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_rag_structured_drafts_content_hash",
        ),
        sa.CheckConstraint(
            "citation_count > 0 AND warning_count >= 0",
            name="ck_rag_structured_drafts_counts",
        ),
    )

    op.create_table(
        "rag_evaluation_results",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("evaluation_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("holdout_sha256", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column(
            "rag_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "rag_generation_runs.id",
                name="fk_rag_evaluation_rag_run_id_rag_runs",
                ondelete="SET NULL",
            ),
        ),
        sa.Column("schema_valid", sa.Boolean(), nullable=False),
        sa.Column("required_sections_present", sa.Boolean(), nullable=False),
        sa.Column("citation_precision", sa.Numeric(6, 5)),
        sa.Column("source_faithfulness_score", sa.Numeric(6, 5)),
        sa.Column(
            "unsupported_claim_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "invented_citation_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("legal_usefulness_score", sa.SmallInteger()),
        sa.Column("legally_relevant", sa.Boolean()),
        sa.Column("correction_count", sa.Integer()),
        sa.Column("evaluator_id", sa.String(128)),
        sa.Column("comments", sa.String(2000)),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "evaluation_run_id",
            "case_id",
            "mode",
            "configuration_hash",
            name="uq_rag_evaluation_identity",
        ),
        sa.CheckConstraint(
            "mode IN ('FAKE','REAL','HUMAN')", name="ck_rag_evaluation_mode"
        ),
        sa.CheckConstraint(
            "holdout_sha256 ~ '^[0-9a-f]{64}$'", name="ck_rag_evaluation_holdout_hash"
        ),
        sa.CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="ck_rag_evaluation_configuration_hash",
        ),
        sa.CheckConstraint(
            "unsupported_claim_count >= 0 AND invented_citation_count >= 0",
            name="ck_rag_evaluation_counts",
        ),
        sa.CheckConstraint("duration_ms >= 0", name="ck_rag_evaluation_duration"),
        sa.CheckConstraint(
            "legal_usefulness_score IS NULL OR legal_usefulness_score BETWEEN 1 AND 5",
            name="ck_rag_evaluation_usefulness",
        ),
        sa.CheckConstraint(
            "citation_precision IS NULL OR citation_precision BETWEEN 0 AND 1",
            name="ck_rag_evaluation_citation_precision",
        ),
        sa.CheckConstraint(
            "source_faithfulness_score IS NULL OR "
            "source_faithfulness_score BETWEEN 0 AND 1",
            name="ck_rag_evaluation_faithfulness",
        ),
        sa.CheckConstraint(
            "correction_count IS NULL OR correction_count >= 0",
            name="ck_rag_evaluation_corrections",
        ),
        sa.CheckConstraint(
            "mode <> 'HUMAN' OR evaluator_id IS NOT NULL",
            name="ck_rag_evaluation_human_evaluator",
        ),
    )


def downgrade() -> None:
    op.drop_table("rag_evaluation_results")
    op.drop_table("rag_structured_drafts")
    op.drop_index("uq_rag_sources_run_context_rank", table_name="rag_retrieved_sources")
    op.drop_table("rag_retrieved_sources")
    op.drop_index("uq_rag_runs_idempotency_active", table_name="rag_generation_runs")
    op.drop_index("ix_rag_runs_request_id", table_name="rag_generation_runs")
    op.drop_index("ix_rag_runs_status_created", table_name="rag_generation_runs")
    op.drop_index("ix_rag_runs_case_created", table_name="rag_generation_runs")
    op.drop_table("rag_generation_runs")
