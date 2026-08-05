"""Minimized search audit and human evaluation ORM mappings."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from legal_ai.domain.semantic_search import SemanticSearchStatus

from .models import Base


def _enum_type(enum_type: type[PyEnum], *, length: int) -> SAEnum:
    return SAEnum(
        enum_type,
        native_enum=False,
        create_constraint=False,
        length=length,
        values_callable=lambda values: [member.value for member in values],
    )


class SemanticSearchRunModel(Base):
    __tablename__ = "semantic_search_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('SUCCEEDED','FAILED')", name="ck_semantic_search_runs_status"
        ),
        CheckConstraint(
            "query_hash ~ '^[0-9a-f]{64}$'", name="ck_semantic_search_runs_query_hash"
        ),
        CheckConstraint(
            "embedding_dimensions = 1024", name="ck_semantic_search_runs_dimensions"
        ),
        CheckConstraint(
            "top_k > 0 AND result_count >= 0 AND duration_ms >= 0",
            name="ck_semantic_search_runs_counts",
        ),
        CheckConstraint(
            "minimum_score IS NULL OR (minimum_score >= 0 AND minimum_score <= 1)",
            name="ck_semantic_search_runs_score",
        ),
        CheckConstraint(
            "btrim(request_id) <> ''", name="ck_semantic_search_runs_request_id"
        ),
        CheckConstraint(
            "jsonb_typeof(filters_sanitized) = 'object' AND "
            "filters_sanitized ?& ARRAY['document_type', 'document_subtype', "
            "'jurisdiction', 'review_status'] AND "
            "(filters_sanitized - ARRAY['document_type', 'document_subtype', "
            "'jurisdiction', 'language', 'organization', 'review_status']) "
            "= '{}'::jsonb AND "
            "jsonb_typeof(filters_sanitized->'document_type') = 'string' AND "
            "filters_sanitized->>'document_type' = 'decreto' AND "
            "jsonb_typeof(filters_sanitized->'document_subtype') = 'string' AND "
            "filters_sanitized->>'document_subtype' = "
            "'designacion_transitoria' AND "
            "jsonb_typeof(filters_sanitized->'jurisdiction') = 'string' AND "
            "filters_sanitized->>'jurisdiction' = 'nacion' AND "
            "jsonb_typeof(filters_sanitized->'review_status') = 'string' AND "
            "filters_sanitized->>'review_status' IN "
            "('REVIEWED', 'PENDING_REVIEW') AND "
            "(NOT filters_sanitized ? 'language' OR "
            "(jsonb_typeof(filters_sanitized->'language') = 'string' AND "
            "filters_sanitized->>'language' = 'es')) AND "
            "(NOT filters_sanitized ? 'organization' OR "
            "(jsonb_typeof(filters_sanitized->'organization') = 'string' AND "
            "btrim(filters_sanitized->>'organization') <> '' AND "
            "length(filters_sanitized->>'organization') <= 200 AND "
            "filters_sanitized->>'organization' !~* "
            "'(authorization|bearer|token|query|storage_path|raw_content|"
            "normalized_content|embedding|vector)'))",
            name="ck_semantic_search_runs_filters_allowlist",
        ),
        CheckConstraint(
            "(status = 'SUCCEEDED' AND error_code IS NULL) OR "
            "(status = 'FAILED' AND error_code IS NOT NULL AND "
            "btrim(error_code) <> '')",
            name="ck_semantic_search_runs_error_code",
        ),
        Index("ix_semantic_search_runs_created", "created_at"),
        Index("ix_semantic_search_runs_status", "status"),
        Index("ix_semantic_search_runs_request", "request_id"),
        Index(
            "ix_semantic_search_runs_model_dimensions",
            "embedding_model",
            "embedding_dimensions",
        ),
        Index("ix_semantic_search_runs_error_code", "error_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    filters_sanitized: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[SemanticSearchStatus] = mapped_column(
        _enum_type(SemanticSearchStatus, length=20), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HumanRetrievalEvaluationModel(Base):
    __tablename__ = "human_retrieval_evaluations"
    __table_args__ = (
        CheckConstraint(
            "usefulness_score BETWEEN 1 AND 5",
            name="ck_human_retrieval_evaluations_score",
        ),
        CheckConstraint(
            "embedding_dimensions = 1024",
            name="ck_human_retrieval_evaluations_dimensions",
        ),
        UniqueConstraint(
            "evaluation_run_id",
            "query_id",
            "result_chunk_id",
            "evaluator_id",
            name="uq_human_retrieval_evaluations_identity",
        ),
        Index("ix_human_retrieval_evaluations_run", "evaluation_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    query_id: Mapped[str] = mapped_column(String(200), nullable=False)
    result_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "corpus_documents.id",
            name="fk_human_retrieval_evaluations_document_id_corpus_documents",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    result_chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "corpus_chunks.id",
            name="fk_human_retrieval_evaluations_chunk_id_corpus_chunks",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    evaluator_id: Mapped[str] = mapped_column(String(200), nullable=False)
    usefulness_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    legally_relevant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    comments: Mapped[str | None] = mapped_column(String(1000))
    dataset_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
