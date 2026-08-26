"""Allow cooperative RAG cancellation and Corrientes document filters."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_semantic_search_runs_filters_allowlist",
        "semantic_search_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_semantic_search_runs_filters_allowlist",
        "semantic_search_runs",
        "jsonb_typeof(filters_sanitized) = 'object' AND "
        "filters_sanitized ?& ARRAY['document_type', 'document_subtype', "
        "'jurisdiction', 'review_status'] AND "
        "(filters_sanitized - ARRAY['document_type', 'document_subtype', "
        "'jurisdiction', 'language', 'organization', 'review_status']) "
        "= '{}'::jsonb AND "
        "jsonb_typeof(filters_sanitized->'document_type') = 'string' AND "
        "filters_sanitized->>'document_type' IN ('decreto', 'disposicion') AND "
        "jsonb_typeof(filters_sanitized->'document_subtype') = 'string' AND "
        "filters_sanitized->>'document_subtype' IN "
        "('designacion', 'designacion_transitoria', 'licencia', 'renuncia', "
        "'contratacion', 'otro') AND "
        "jsonb_typeof(filters_sanitized->'jurisdiction') = 'string' AND "
        "filters_sanitized->>'jurisdiction' IN ('nacion', 'corrientes') AND "
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
        "'(authorization|bearer|token|query|storage_path|raw_content|"
        "normalized_content|embedding|vector)')",
    )
    op.drop_constraint(
        "ck_rag_generation_runs_status", "rag_generation_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_rag_generation_runs_status",
        "rag_generation_runs",
        "status IN ('PENDING','RETRIEVING','GENERATING','VALIDATING','SUCCEEDED',"
        "'FAILED','CANCELLED')",
    )
    op.drop_constraint(
        "ck_rag_runs_terminal_state", "rag_generation_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_rag_runs_terminal_state",
        "rag_generation_runs",
        "(status = 'SUCCEEDED' AND draft_id IS NOT NULL "
        "AND context_hash IS NOT NULL AND prompt_hash IS NOT NULL "
        "AND finished_at IS NOT NULL AND selected_count > 0 "
        "AND error_code IS NULL) OR "
        "(status IN ('FAILED','CANCELLED') AND finished_at IS NOT NULL "
        "AND error_code IS NOT NULL AND btrim(error_code) <> '' "
        "AND draft_id IS NULL) OR "
        "(status NOT IN ('SUCCEEDED','FAILED','CANCELLED') AND finished_at IS NULL "
        "AND draft_id IS NULL)",
    )
    op.drop_index("uq_rag_runs_idempotency_active", table_name="rag_generation_runs")
    op.create_index(
        "uq_rag_runs_idempotency_active",
        "rag_generation_runs",
        ["idempotency_key_hash"],
        unique=True,
        postgresql_where=sa.text(
            "idempotency_key_hash IS NOT NULL AND status NOT IN ('FAILED','CANCELLED')"
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_semantic_search_runs_filters_allowlist",
        "semantic_search_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_semantic_search_runs_filters_allowlist",
        "semantic_search_runs",
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
        "'(authorization|bearer|token|query|storage_path|raw_content|"
        "normalized_content|embedding|vector)')",
    )
    op.drop_index("uq_rag_runs_idempotency_active", table_name="rag_generation_runs")
    op.create_index(
        "uq_rag_runs_idempotency_active",
        "rag_generation_runs",
        ["idempotency_key_hash"],
        unique=True,
        postgresql_where=sa.text(
            "idempotency_key_hash IS NOT NULL AND status <> 'FAILED'"
        ),
    )
    op.drop_constraint(
        "ck_rag_runs_terminal_state", "rag_generation_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_rag_runs_terminal_state",
        "rag_generation_runs",
        "(status = 'SUCCEEDED' AND draft_id IS NOT NULL "
        "AND context_hash IS NOT NULL AND prompt_hash IS NOT NULL "
        "AND finished_at IS NOT NULL AND selected_count > 0 "
        "AND error_code IS NULL) OR "
        "(status = 'FAILED' AND finished_at IS NOT NULL AND error_code IS NOT NULL "
        "AND btrim(error_code) <> '' AND draft_id IS NULL) OR "
        "(status NOT IN ('SUCCEEDED','FAILED') AND finished_at IS NULL "
        "AND draft_id IS NULL)",
    )
    op.drop_constraint(
        "ck_rag_generation_runs_status", "rag_generation_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_rag_generation_runs_status",
        "rag_generation_runs",
        "status IN ('PENDING','RETRIEVING','GENERATING','VALIDATING',"
        "'SUCCEEDED','FAILED')",
    )
