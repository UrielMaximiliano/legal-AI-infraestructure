"""005 corpus ingestion and semantic retrieval.

The migration is intentionally self-contained: it creates only 005 objects,
uses the extension enabled by 001, and never drops ``vector`` on downgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "005"
down_revision = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(column: str, values: tuple[str, ...], name: str) -> sa.CheckConstraint:
    quoted = ",".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({quoted})", name=name)


def _json_default(value: str = "{}") -> sa.TextClause:
    return sa.text(f"'{value}'::jsonb")


def upgrade() -> None:
    """Create the reversible 005 persistence model."""
    op.create_table(
        "corpus_documents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("external_id", sa.String(256), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("document_subtype", sa.String(100), nullable=False),
        sa.Column("jurisdiction", sa.String(120), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("organization", sa.String(200), nullable=True),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_identifier", sa.String(512), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("raw_content_hash", sa.String(64), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("normalized_content_hash", sa.String(64), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default=_json_default()),
        sa.Column(
            "provenance_type", sa.String(20), nullable=False, server_default="AUTOMATED"
        ),
        sa.Column(
            "review_status",
            sa.String(20),
            nullable=False,
            server_default="PENDING_REVIEW",
        ),
        sa.Column("review_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reviewed_by", sa.String(200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column(
            "ingestion_status",
            sa.String(30),
            nullable=False,
            server_default="DISCOVERED",
        ),
        sa.Column(
            "embedding_status", sa.String(30), nullable=False, server_default="PENDING"
        ),
        sa.Column("created_by_pipeline_version", sa.String(100), nullable=False),
        sa.Column("normalization_version", sa.String(100), nullable=False),
        sa.Column("chunking_version", sa.String(100), nullable=False),
        sa.Column("active_generation", sa.Integer(), nullable=True),
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
        _check(
            "provenance_type",
            ("AUTOMATED", "HUMAN_REVIEWED"),
            "ck_corpus_documents_provenance",
        ),
        _check(
            "review_status",
            ("PENDING_REVIEW", "REVIEWED", "REJECTED"),
            "ck_corpus_documents_review_status",
        ),
        _check(
            "ingestion_status",
            (
                "DISCOVERED",
                "PARSED",
                "NORMALIZED",
                "VALIDATED",
                "CHUNKED",
                "EMBEDDING",
                "INDEXED",
                "COMPLETED",
                "FAILED",
            ),
            "ck_corpus_documents_ingestion_status",
        ),
        _check(
            "embedding_status",
            ("PENDING", "PROCESSING", "EMBEDDED", "FAILED"),
            "ck_corpus_documents_embedding_status",
        ),
        sa.CheckConstraint(
            "review_version > 0", name="ck_corpus_documents_review_version_positive"
        ),
        sa.CheckConstraint(
            "(review_status = 'PENDING_REVIEW' AND reviewed_by IS NULL AND "
            "reviewed_at IS NULL) "
            "OR (review_status IN ('REVIEWED', 'REJECTED') AND reviewed_by IS NOT NULL "
            "AND btrim(reviewed_by) <> '' AND reviewed_at IS NOT NULL)",
            name="ck_corpus_documents_review_metadata",
        ),
        sa.CheckConstraint(
            "review_status = 'PENDING_REVIEW' OR provenance_type = 'HUMAN_REVIEWED'",
            name="ck_corpus_documents_review_provenance",
        ),
        sa.CheckConstraint(
            "review_status <> 'REJECTED' OR (review_notes IS NOT NULL AND "
            "btrim(review_notes) <> '')",
            name="ck_corpus_documents_rejection_reason",
        ),
        sa.CheckConstraint(
            "btrim(raw_content) <> ''", name="ck_corpus_documents_raw_not_empty"
        ),
        sa.CheckConstraint(
            "ingestion_status IN ('DISCOVERED', 'FAILED') OR "
            "btrim(normalized_content) <> ''",
            name="ck_corpus_documents_normalized_not_empty",
        ),
        sa.CheckConstraint(
            "active_generation IS NULL OR active_generation > 0",
            name="ck_corpus_documents_active_generation_positive",
        ),
        sa.CheckConstraint(
            "source_url IS NULL OR source_url ~ '^https://'",
            name="ck_corpus_documents_source_url_https",
        ),
        sa.CheckConstraint(
            "raw_content_hash ~ '^[0-9a-f]{64}$'", name="ck_corpus_documents_raw_hash"
        ),
        sa.CheckConstraint(
            "normalized_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_corpus_documents_normalized_hash",
        ),
    )
    op.create_table(
        "corpus_chunks",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "corpus_documents.id",
                name="fk_corpus_chunks_document_id_corpus_documents",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", sa.String(20), nullable=False, server_default="STAGED"),
        sa.Column("section_type", sa.String(40), nullable=False),
        sa.Column("section_index", sa.Integer(), nullable=False),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("article_number", sa.String(64), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embedding_model", sa.String(200), nullable=True),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column("normalization_version", sa.String(100), nullable=False),
        sa.Column("chunking_version", sa.String(100), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default=_json_default()),
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
        _check(
            "state",
            ("STAGED", "EMBEDDING", "ACTIVE", "FAILED", "SUPERSEDED"),
            "ck_corpus_chunks_state",
        ),
        sa.CheckConstraint(
            "generation > 0", name="ck_corpus_chunks_generation_positive"
        ),
        sa.CheckConstraint(
            "section_index >= 0 AND (paragraph_index IS NULL OR paragraph_index >= 0)",
            name="ck_corpus_chunks_indexes_nonnegative",
        ),
        sa.CheckConstraint(
            "token_count >= 0", name="ck_corpus_chunks_token_count_nonnegative"
        ),
        sa.CheckConstraint("content <> ''", name="ck_corpus_chunks_content_not_empty"),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_corpus_chunks_content_hash"
        ),
        sa.CheckConstraint(
            "embedding_dimensions IS NULL OR embedding_dimensions = 1024",
            name="ck_corpus_chunks_embedding_dimensions",
        ),
        sa.CheckConstraint(
            "embedding IS NULL OR (embedding_model IS NOT NULL AND "
            "embedding_dimensions = 1024)",
            name="ck_corpus_chunks_embedding_model",
        ),
        sa.CheckConstraint(
            "state <> 'ACTIVE' OR embedding IS NOT NULL",
            name="ck_corpus_chunks_active_embedding",
        ),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("run_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("source_identifier", sa.String(512), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column(
            "configuration_snapshot",
            JSONB(),
            nullable=False,
            server_default=_json_default(),
        ),
        sa.Column("counts", JSONB(), nullable=False, server_default=_json_default()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resume_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_summary", sa.String(500), nullable=True),
        _check("run_type", ("INGEST", "REINDEX"), "ck_ingestion_runs_type"),
        _check(
            "status",
            ("PENDING", "RUNNING", "COMPLETED", "PARTIAL", "FAILED", "INTERRUPTED"),
            "ck_ingestion_runs_status",
        ),
        sa.CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ingestion_runs_configuration_hash",
        ),
        sa.CheckConstraint("resume_count >= 0", name="ck_ingestion_runs_resume_count"),
        sa.CheckConstraint(
            "(status IN ('COMPLETED','PARTIAL','FAILED') AND finished_at IS NOT "
            "NULL) OR "
            "(status IN ('PENDING','RUNNING','INTERRUPTED') AND finished_at IS NULL)",
            name="ck_ingestion_runs_finished_at",
        ),
        sa.CheckConstraint(
            "status NOT IN ('FAILED','INTERRUPTED') OR "
            "(error_code IS NOT NULL AND btrim(error_code) <> '')",
            name="ck_ingestion_runs_error_code",
        ),
        sa.UniqueConstraint("run_id", name="uq_ingestion_runs_run_id"),
    )
    op.create_table(
        "embedding_batches",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ingestion_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "ingestion_runs.id",
                name="fk_embedding_batches_ingestion_run_id_ingestion_runs",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "chunk_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("input_count", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        _check(
            "status",
            ("PENDING", "PROCESSING", "SUCCEEDED", "FAILED_RETRYABLE", "FAILED_FINAL"),
            "ck_embedding_batches_status",
        ),
        sa.CheckConstraint(
            "generation > 0 AND batch_index >= 0", name="ck_embedding_batches_indexes"
        ),
        sa.CheckConstraint(
            "input_count >= 0 AND attempt_count >= 0",
            name="ck_embedding_batches_counts",
        ),
        sa.CheckConstraint(
            "embedding_dimensions = 1024", name="ck_embedding_batches_dimensions"
        ),
        sa.UniqueConstraint(
            "ingestion_run_id",
            "generation",
            "batch_index",
            name="uq_embedding_batches_run_generation_index",
        ),
    )
    op.create_table(
        "ingestion_failures",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ingestion_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "ingestion_runs.id",
                name="fk_ingestion_failures_ingestion_run_id_ingestion_runs",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("source_identifier", sa.String(512), nullable=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "corpus_documents.id",
                name="fk_ingestion_failures_document_id_corpus_documents",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "embedding_batches.id",
                name="fk_ingestion_failures_batch_id_embedding_batches",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "semantic_search_runs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column(
            "filters_sanitized", JSONB(), nullable=False, server_default=_json_default()
        ),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("minimum_score", sa.Float(), nullable=True),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        _check("status", ("SUCCEEDED", "FAILED"), "ck_semantic_search_runs_status"),
        sa.CheckConstraint(
            "query_hash ~ '^[0-9a-f]{64}$'", name="ck_semantic_search_runs_query_hash"
        ),
        sa.CheckConstraint(
            "embedding_dimensions = 1024", name="ck_semantic_search_runs_dimensions"
        ),
        sa.CheckConstraint(
            "top_k > 0 AND result_count >= 0 AND duration_ms >= 0",
            name="ck_semantic_search_runs_counts",
        ),
        sa.CheckConstraint(
            "minimum_score IS NULL OR (minimum_score >= 0 AND minimum_score <= 1)",
            name="ck_semantic_search_runs_score",
        ),
        sa.CheckConstraint(
            "btrim(request_id) <> ''",
            name="ck_semantic_search_runs_request_id",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(filters_sanitized) = 'object' AND "
            "filters_sanitized ?& ARRAY['document_type', 'document_subtype', "
            "'jurisdiction', 'review_status'] AND "
            "(filters_sanitized - ARRAY['document_type', 'document_subtype', "
            "'jurisdiction', 'language', 'organization', 'review_status']) "
            "= '{}'::jsonb AND "
            "jsonb_typeof(filters_sanitized->'document_type') = 'string' AND "
            "filters_sanitized->>'document_type' = 'decreto' AND "
            "jsonb_typeof(filters_sanitized->'document_subtype') = 'string' AND "
            "filters_sanitized->>'document_subtype' = 'designacion_transitoria' AND "
            "jsonb_typeof(filters_sanitized->'jurisdiction') = 'string' AND "
            "filters_sanitized->>'jurisdiction' = 'nacion' AND "
            "jsonb_typeof(filters_sanitized->'review_status') = 'string' AND "
            "filters_sanitized->>'review_status' IN ('REVIEWED', 'PENDING_REVIEW') AND "
            "(NOT filters_sanitized ? 'language' OR "
            "(jsonb_typeof(filters_sanitized->'language') = 'string' AND "
            "filters_sanitized->>'language' = 'es')) AND "
            "(NOT filters_sanitized ? 'organization' OR "
            "(jsonb_typeof(filters_sanitized->'organization') = 'string' AND "
            "btrim(filters_sanitized->>'organization') <> '' AND "
            "length(filters_sanitized->>'organization') <= 200 AND "
            "filters_sanitized->>'organization' !~* "
            "'(authorization|bearer|token|query|storage_path|raw_content|normalized_content|embedding|vector)'))",
            name="ck_semantic_search_runs_filters_allowlist",
        ),
        sa.CheckConstraint(
            "(status = 'SUCCEEDED' AND error_code IS NULL) OR "
            "(status = 'FAILED' AND error_code IS NOT NULL AND "
            "btrim(error_code) <> '')",
            name="ck_semantic_search_runs_error_code",
        ),
    )
    op.create_table(
        "human_retrieval_evaluations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("evaluation_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query_id", sa.String(200), nullable=False),
        sa.Column(
            "result_document_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "corpus_documents.id",
                name="fk_human_retrieval_evaluations_document_id_corpus_documents",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "result_chunk_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "corpus_chunks.id",
                name="fk_human_retrieval_evaluations_chunk_id_corpus_chunks",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("evaluator_id", sa.String(200), nullable=False),
        sa.Column("usefulness_score", sa.SmallInteger(), nullable=False),
        sa.Column("legally_relevant", sa.Boolean(), nullable=False),
        sa.Column("comments", sa.String(1000), nullable=True),
        sa.Column("dataset_version", sa.String(100), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "usefulness_score BETWEEN 1 AND 5",
            name="ck_human_retrieval_evaluations_score",
        ),
        sa.CheckConstraint(
            "embedding_dimensions = 1024",
            name="ck_human_retrieval_evaluations_dimensions",
        ),
        sa.UniqueConstraint(
            "evaluation_run_id",
            "query_id",
            "result_chunk_id",
            "evaluator_id",
            name="uq_human_retrieval_evaluations_identity",
        ),
    )

    # Generation swaps are allowed to stage several row changes in one
    # transaction.  A deferred constraint trigger validates the final state:
    # one active generation per document, every ACTIVE chunk belongs to it,
    # and the document pointer cannot refer to a generation that does not
    # exist.  This keeps the swap atomic without blocking valid intermediate
    # states of the ingestion pipeline.
    op.execute(
        sa.text(
            """
            CREATE FUNCTION validate_corpus_active_generation_005()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                affected_document_id uuid;
                affected_document_ids uuid[] := ARRAY[]::uuid[];
                validated_document_ids uuid[] := ARRAY[]::uuid[];
                active_generation_value integer;
            BEGIN
                IF TG_TABLE_NAME = 'corpus_documents' THEN
                    IF TG_OP = 'DELETE' THEN
                        affected_document_ids := ARRAY[OLD.id];
                    ELSIF TG_OP = 'UPDATE' THEN
                        affected_document_ids := ARRAY[OLD.id, NEW.id];
                    ELSE
                        affected_document_ids := ARRAY[NEW.id];
                    END IF;
                ELSE
                    IF TG_OP = 'DELETE' THEN
                        affected_document_ids := ARRAY[OLD.document_id];
                    ELSIF TG_OP = 'UPDATE' THEN
                        affected_document_ids := ARRAY[
                            OLD.document_id, NEW.document_id
                        ];
                    ELSE
                        affected_document_ids := ARRAY[NEW.document_id];
                    END IF;
                END IF;

                SELECT array_agg(id ORDER BY id)
                  INTO affected_document_ids
                  FROM (
                      SELECT DISTINCT unnest(affected_document_ids) AS id
                  ) AS affected
                 WHERE id IS NOT NULL;

                FOREACH affected_document_id IN ARRAY affected_document_ids LOOP
                    IF affected_document_id IS NULL OR
                       affected_document_id = ANY(validated_document_ids) THEN
                        CONTINUE;
                    END IF;
                    validated_document_ids := array_append(
                        validated_document_ids, affected_document_id
                    );

                    SELECT active_generation
                      INTO active_generation_value
                      FROM corpus_documents
                     WHERE id = affected_document_id
                     FOR UPDATE;

                    IF NOT FOUND THEN
                        CONTINUE;
                    END IF;

                    IF active_generation_value IS NULL THEN
                        IF EXISTS (
                            SELECT 1 FROM corpus_chunks
                             WHERE document_id = affected_document_id
                               AND state = 'ACTIVE'
                        ) THEN
                            RAISE EXCEPTION 'CORPUS_ACTIVE_GENERATION_REQUIRED';
                        END IF;
                    ELSE
                        IF NOT EXISTS (
                            SELECT 1 FROM corpus_chunks
                             WHERE document_id = affected_document_id
                               AND generation = active_generation_value
                        ) THEN
                            RAISE EXCEPTION 'CORPUS_ACTIVE_GENERATION_NOT_FOUND';
                        END IF;
                        IF EXISTS (
                            SELECT 1 FROM corpus_chunks
                             WHERE document_id = affected_document_id
                               AND state = 'ACTIVE'
                               AND generation <> active_generation_value
                        ) THEN
                            RAISE EXCEPTION 'CORPUS_ACTIVE_GENERATION_MISMATCH';
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM corpus_chunks
                             WHERE document_id = affected_document_id
                               AND state = 'ACTIVE'
                               AND generation = active_generation_value
                        ) THEN
                            RAISE EXCEPTION 'CORPUS_ACTIVE_GENERATION_CHUNK_REQUIRED';
                        END IF;
                    END IF;

                    IF (
                        SELECT count(DISTINCT generation)
                          FROM corpus_chunks
                         WHERE document_id = affected_document_id
                           AND state = 'ACTIVE'
                    ) > 1 THEN
                        RAISE EXCEPTION 'CORPUS_MULTIPLE_ACTIVE_GENERATIONS';
                    END IF;
                END LOOP;
                RETURN NULL;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_corpus_documents_active_generation_005
            AFTER INSERT OR UPDATE OR DELETE ON corpus_documents
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION validate_corpus_active_generation_005();
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_corpus_chunks_active_generation_005
            AFTER INSERT OR UPDATE OR DELETE ON corpus_chunks
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION validate_corpus_active_generation_005();
            """
        )
    )

    op.create_index(
        "ix_corpus_documents_review_status", "corpus_documents", ["review_status"]
    )
    op.create_index(
        "ix_corpus_documents_search_filters",
        "corpus_documents",
        ["document_type", "document_subtype", "jurisdiction", "review_status"],
    )
    op.create_index(
        "ix_corpus_documents_source_identifier",
        "corpus_documents",
        ["source_identifier"],
    )
    op.create_index(
        "ix_corpus_documents_hashes",
        "corpus_documents",
        ["raw_content_hash", "normalized_content_hash"],
    )
    op.create_index(
        "ix_corpus_chunks_document_generation",
        "corpus_chunks",
        ["document_id", "generation"],
    )
    op.create_index("ix_corpus_chunks_state", "corpus_chunks", ["state"])
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])
    op.create_index(
        "ix_ingestion_failures_run", "ingestion_failures", ["ingestion_run_id"]
    )
    op.create_index(
        "ix_semantic_search_runs_created", "semantic_search_runs", ["created_at"]
    )
    op.create_index(
        "ix_semantic_search_runs_status", "semantic_search_runs", ["status"]
    )
    op.create_index(
        "ix_semantic_search_runs_request", "semantic_search_runs", ["request_id"]
    )
    op.create_index(
        "ix_semantic_search_runs_model_dimensions",
        "semantic_search_runs",
        ["embedding_model", "embedding_dimensions"],
    )
    op.create_index(
        "ix_semantic_search_runs_error_code", "semantic_search_runs", ["error_code"]
    )
    op.create_index(
        "ix_human_retrieval_evaluations_run",
        "human_retrieval_evaluations",
        ["evaluation_run_id"],
    )
    op.create_index(
        "uq_corpus_documents_source_external",
        "corpus_documents",
        ["source_name", "external_id"],
        unique=True,
        postgresql_where=sa.text("ingestion_status <> 'FAILED'"),
    )
    op.create_index(
        "uq_corpus_documents_identity_active",
        "corpus_documents",
        ["source_identifier", "raw_content_hash", "normalized_content_hash"],
        unique=True,
        postgresql_where=sa.text(
            "active_generation IS NOT NULL AND ingestion_status <> 'FAILED'"
        ),
    )
    op.create_index(
        "uq_corpus_chunks_document_generation_position",
        "corpus_chunks",
        ["document_id", "generation", "section_index", "paragraph_index"],
        unique=True,
    )
    op.create_index(
        "uq_corpus_chunks_document_generation_hash",
        "corpus_chunks",
        ["document_id", "generation", "content_hash"],
        unique=True,
    )


def downgrade() -> None:
    """Drop only objects introduced by revision 005."""
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_corpus_chunks_active_generation_005 "
            "ON corpus_chunks"
        )
    )
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_corpus_documents_active_generation_005 "
            "ON corpus_documents"
        )
    )
    op.execute(
        sa.text("DROP FUNCTION IF EXISTS validate_corpus_active_generation_005()")
    )
    for index_name, _table in (
        ("uq_corpus_chunks_document_generation_hash", "corpus_chunks"),
        ("uq_corpus_chunks_document_generation_position", "corpus_chunks"),
        ("uq_corpus_documents_source_external", "corpus_documents"),
        ("uq_corpus_documents_identity_active", "corpus_documents"),
        ("ix_human_retrieval_evaluations_run", "human_retrieval_evaluations"),
        ("ix_semantic_search_runs_error_code", "semantic_search_runs"),
        ("ix_semantic_search_runs_model_dimensions", "semantic_search_runs"),
        ("ix_semantic_search_runs_request", "semantic_search_runs"),
        ("ix_semantic_search_runs_status", "semantic_search_runs"),
        ("ix_semantic_search_runs_created", "semantic_search_runs"),
        ("ix_ingestion_failures_run", "ingestion_failures"),
        ("ix_ingestion_runs_status", "ingestion_runs"),
        ("ix_corpus_chunks_state", "corpus_chunks"),
        ("ix_corpus_chunks_document_generation", "corpus_chunks"),
        ("ix_corpus_documents_hashes", "corpus_documents"),
        ("ix_corpus_documents_search_filters", "corpus_documents"),
        ("ix_corpus_documents_source_identifier", "corpus_documents"),
        ("ix_corpus_documents_review_status", "corpus_documents"),
    ):
        op.execute(sa.text(f'DROP INDEX IF EXISTS "{index_name}"'))
    for table in (
        "human_retrieval_evaluations",
        "semantic_search_runs",
        "ingestion_failures",
        "embedding_batches",
        "ingestion_runs",
        "corpus_chunks",
        "corpus_documents",
    ):
        op.drop_table(table)
