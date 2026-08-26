"""SQLAlchemy models for RAG audit and evaluation tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from legal_ai.adapters.database.models import Base


class RagGenerationRunModel(Base):
    __tablename__ = "rag_generation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'PENDING','RETRIEVING','GENERATING','VALIDATING','SUCCEEDED','FAILED',"
            "'CANCELLED'"
            ")",
            name="ck_rag_generation_runs_status",
        ),
        CheckConstraint("embedding_dimensions = 2560", name="ck_rag_runs_dimensions"),
        CheckConstraint(
            "embedding_model = 'qwen3-embedding:4b-q4_K_M'",
            name="ck_rag_runs_embedding_model",
        ),
        CheckConstraint(
            "generation_model = 'qwen3.6:35b'", name="ck_rag_runs_generation_model"
        ),
        CheckConstraint("schema_version > 0", name="ck_rag_runs_schema_version"),
        CheckConstraint(
            "btrim(embedding_model) <> '' AND btrim(generation_model) <> '' AND "
            "btrim(prompt_version) <> ''",
            name="ck_rag_runs_metadata_nonempty",
        ),
        CheckConstraint(
            "top_k BETWEEN 3 AND 20 AND candidate_pool_size BETWEEN top_k AND 50",
            name="ck_rag_runs_retrieval_limits",
        ),
        CheckConstraint(
            "minimum_score IS NULL OR (minimum_score >= 0 AND minimum_score <= 1)",
            name="ck_rag_runs_score",
        ),
        CheckConstraint(
            "retrieved_count >= 0 AND selected_count >= 0 AND "
            "selected_count <= retrieved_count AND context_bytes >= 0 AND "
            "context_tokens_estimate >= 0",
            name="ck_rag_runs_counts",
        ),
        CheckConstraint(
            "schema_repair_count BETWEEN 0 AND 1", name="ck_rag_runs_repair_count"
        ),
        CheckConstraint(
            "(retrieval_duration_ms IS NULL OR retrieval_duration_ms >= 0) AND "
            "(generation_duration_ms IS NULL OR generation_duration_ms >= 0) AND "
            "(validation_duration_ms IS NULL OR validation_duration_ms >= 0) AND "
            "(total_duration_ms IS NULL OR total_duration_ms >= 0)",
            name="ck_rag_runs_durations",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$' AND query_hash ~ '^[0-9a-f]{64}$' AND "
            "(idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$')",
            name="ck_rag_runs_hashes",
        ),
        CheckConstraint(
            "(status = 'SUCCEEDED' AND draft_id IS NOT NULL "
            "AND context_hash IS NOT NULL AND prompt_hash IS NOT NULL "
            "AND finished_at IS NOT NULL AND selected_count > 0 "
            "AND error_code IS NULL) OR "
            "(status IN ('FAILED','CANCELLED') AND finished_at IS NOT NULL "
            "AND error_code IS NOT NULL "
            "AND btrim(error_code) <> '' AND draft_id IS NULL) OR "
            "(status NOT IN ('SUCCEEDED','FAILED','CANCELLED') AND finished_at IS NULL "
            "AND draft_id IS NULL)",
            name="ck_rag_runs_terminal_state",
        ),
        CheckConstraint("btrim(request_id) <> ''", name="ck_rag_runs_request_id"),
        Index("ix_rag_runs_case_created", "case_file_id", "created_at"),
        Index("ix_rag_runs_status_created", "status", "created_at"),
        Index("ix_rag_runs_request_id", "request_id"),
        Index(
            "uq_rag_runs_idempotency_active",
            "idempotency_key_hash",
            unique=True,
            postgresql_where=text(
                "idempotency_key_hash IS NOT NULL AND "
                "status NOT IN ('FAILED','CANCELLED')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    generation_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "generation_attempts.id",
            name="fk_rag_runs_generation_attempt_id_generation_attempts",
            ondelete="SET NULL",
        ),
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "document_drafts.id",
            name="fk_rag_runs_draft_id_document_drafts",
            ondelete="SET NULL",
        ),
    )
    case_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "case_files.id",
            name="fk_rag_runs_case_file_id_case_files",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "document_templates.id",
            name="fk_rag_runs_template_id_document_templates",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context_hash: Mapped[str | None] = mapped_column(String(64))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_pool_size: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    retrieved_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    selected_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    context_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    context_tokens_estimate: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    schema_repair_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    retrieval_duration_ms: Mapped[int | None] = mapped_column(Integer)
    generation_duration_ms: Mapped[int | None] = mapped_column(Integer)
    validation_duration_ms: Mapped[int | None] = mapped_column(Integer)
    total_duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RagRetrievedSourceModel(Base):
    __tablename__ = "rag_retrieved_sources"
    __table_args__ = (
        UniqueConstraint("run_id", "chunk_id", name="uq_rag_sources_run_chunk"),
        UniqueConstraint(
            "run_id", "retrieval_rank", name="uq_rag_sources_run_retrieval_rank"
        ),
        UniqueConstraint("run_id", "citation_id", name="uq_rag_sources_run_citation"),
        CheckConstraint("retrieval_rank > 0", name="ck_rag_sources_retrieval_rank"),
        CheckConstraint(
            "context_rank IS NULL OR context_rank > 0",
            name="ck_rag_sources_context_rank",
        ),
        CheckConstraint(
            "similarity_score BETWEEN 0 AND 1", name="ck_rag_sources_score"
        ),
        CheckConstraint("generation > 0", name="ck_rag_sources_generation"),
        CheckConstraint("btrim(section_type) <> ''", name="ck_rag_sources_section"),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_rag_sources_content_hash"
        ),
        CheckConstraint(
            "disposition IN ("
            "'SELECTED','EXCLUDED_BUDGET','EXCLUDED_DIVERSITY','EXCLUDED_SCORE'"
            ")",
            name="ck_rag_sources_disposition",
        ),
        CheckConstraint(
            "(disposition = 'SELECTED' AND context_rank IS NOT NULL) OR "
            "(disposition <> 'SELECTED' AND context_rank IS NULL)",
            name="ck_rag_sources_context_disposition",
        ),
        Index(
            "uq_rag_sources_run_context_rank",
            "run_id",
            "context_rank",
            unique=True,
            postgresql_where=text("context_rank IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "rag_generation_runs.id",
            name="fk_rag_sources_run_id_rag_runs",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "corpus_documents.id",
            name="fk_rag_sources_document_id_corpus_documents",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "corpus_chunks.id",
            name="fk_rag_sources_chunk_id_corpus_chunks",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    citation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieval_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    context_rank: Mapped[int | None] = mapped_column(Integer)
    similarity_score: Mapped[Decimal] = mapped_column(Numeric(8, 7), nullable=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    section_type: Mapped[str] = mapped_column(String(40), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RagStructuredDraftModel(Base):
    __tablename__ = "rag_structured_drafts"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_rag_structured_drafts_run"),
        UniqueConstraint("draft_id", name="uq_rag_structured_drafts_draft"),
        CheckConstraint(
            "schema_version > 0", name="ck_rag_structured_drafts_schema_version"
        ),
        CheckConstraint(
            "jsonb_typeof(content_json) = 'object'",
            name="ck_rag_structured_drafts_json_object",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_rag_structured_drafts_content_hash",
        ),
        CheckConstraint(
            "citation_count > 0 AND warning_count >= 0",
            name="ck_rag_structured_drafts_counts",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "rag_generation_runs.id",
            name="fk_rag_structured_drafts_run_id_rag_runs",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "document_drafts.id",
            name="fk_rag_structured_drafts_draft_id_document_drafts",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RagEvaluationResultModel(Base):
    __tablename__ = "rag_evaluation_results"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id",
            "case_id",
            "mode",
            "configuration_hash",
            name="uq_rag_evaluation_identity",
        ),
        CheckConstraint(
            "mode IN ('FAKE','REAL','HUMAN')", name="ck_rag_evaluation_mode"
        ),
        CheckConstraint(
            "holdout_sha256 ~ '^[0-9a-f]{64}$'", name="ck_rag_evaluation_holdout_hash"
        ),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="ck_rag_evaluation_configuration_hash",
        ),
        CheckConstraint(
            "unsupported_claim_count >= 0 AND invented_citation_count >= 0",
            name="ck_rag_evaluation_counts",
        ),
        CheckConstraint("duration_ms >= 0", name="ck_rag_evaluation_duration"),
        CheckConstraint(
            "legal_usefulness_score IS NULL OR legal_usefulness_score BETWEEN 1 AND 5",
            name="ck_rag_evaluation_usefulness",
        ),
        CheckConstraint(
            "citation_precision IS NULL OR citation_precision BETWEEN 0 AND 1",
            name="ck_rag_evaluation_citation_precision",
        ),
        CheckConstraint(
            "source_faithfulness_score IS NULL OR "
            "source_faithfulness_score BETWEEN 0 AND 1",
            name="ck_rag_evaluation_faithfulness",
        ),
        CheckConstraint(
            "correction_count IS NULL OR correction_count >= 0",
            name="ck_rag_evaluation_corrections",
        ),
        CheckConstraint(
            "mode <> 'HUMAN' OR evaluator_id IS NOT NULL",
            name="ck_rag_evaluation_human_evaluator",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    holdout_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rag_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "rag_generation_runs.id",
            name="fk_rag_evaluation_rag_run_id_rag_runs",
            ondelete="SET NULL",
        ),
    )
    schema_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_sections_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    citation_precision: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    source_faithfulness_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    unsupported_claim_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    invented_citation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    legal_usefulness_score: Mapped[int | None] = mapped_column(SmallInteger)
    legally_relevant: Mapped[bool | None] = mapped_column(Boolean)
    correction_count: Mapped[int | None] = mapped_column(Integer)
    evaluator_id: Mapped[str | None] = mapped_column(String(128))
    comments: Mapped[str | None] = mapped_column(String(2000))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
