"""ORM mappings for ingestion runs, failures and embedding batches."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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

from legal_ai.domain.ingestion import EmbeddingBatchStatus, IngestionRunStatus

from .models import Base


def _enum_type(enum_type: type[PyEnum], *, length: int) -> SAEnum:
    return SAEnum(
        enum_type,
        native_enum=False,
        create_constraint=False,
        length=length,
        values_callable=lambda values: [member.value for member in values],
    )


class IngestionRunModel(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "run_type IN ('INGEST','REINDEX')", name="ck_ingestion_runs_type"
        ),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','PARTIAL','FAILED',"
            "'INTERRUPTED')",
            name="ck_ingestion_runs_status",
        ),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ingestion_runs_configuration_hash",
        ),
        CheckConstraint("resume_count >= 0", name="ck_ingestion_runs_resume_count"),
        CheckConstraint(
            "(status IN ('COMPLETED','PARTIAL','FAILED') AND finished_at IS NOT "
            "NULL) OR (status IN ('PENDING','RUNNING','INTERRUPTED') AND "
            "finished_at IS NULL)",
            name="ck_ingestion_runs_finished_at",
        ),
        CheckConstraint(
            "status NOT IN ('FAILED','INTERRUPTED') OR (error_code IS NOT NULL "
            "AND btrim(error_code) <> '')",
            name="ck_ingestion_runs_error_code",
        ),
        UniqueConstraint("run_id", name="uq_ingestion_runs_run_id"),
        Index("ix_ingestion_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    run_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[IngestionRunStatus] = mapped_column(
        _enum_type(IngestionRunStatus, length=20),
        nullable=False,
        default=IngestionRunStatus.PENDING,
        server_default="PENDING",
    )
    source_identifier: Mapped[str] = mapped_column(String(512), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    counts: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resume_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_summary: Mapped[str | None] = mapped_column(String(500))


class EmbeddingBatchModel(Base):
    __tablename__ = "embedding_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','SUCCEEDED','FAILED_RETRYABLE',"
            "'FAILED_FINAL')",
            name="ck_embedding_batches_status",
        ),
        CheckConstraint(
            "generation > 0 AND batch_index >= 0", name="ck_embedding_batches_indexes"
        ),
        CheckConstraint(
            "input_count >= 0 AND attempt_count >= 0",
            name="ck_embedding_batches_counts",
        ),
        CheckConstraint(
            "embedding_dimensions = 1024", name="ck_embedding_batches_dimensions"
        ),
        UniqueConstraint(
            "ingestion_run_id",
            "generation",
            "batch_index",
            name="uq_embedding_batches_run_generation_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "ingestion_runs.id",
            name="fk_embedding_batches_ingestion_run_id_ingestion_runs",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[EmbeddingBatchStatus] = mapped_column(
        _enum_type(EmbeddingBatchStatus, length=20),
        nullable=False,
        default=EmbeddingBatchStatus.PENDING,
        server_default="PENDING",
    )
    chunk_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    input_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))


class IngestionFailureModel(Base):
    __tablename__ = "ingestion_failures"
    __table_args__ = (Index("ix_ingestion_failures_run", "ingestion_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "ingestion_runs.id",
            name="fk_ingestion_failures_ingestion_run_id_ingestion_runs",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    source_identifier: Mapped[str | None] = mapped_column(String(512))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "corpus_documents.id",
            name="fk_ingestion_failures_document_id_corpus_documents",
            ondelete="SET NULL",
        )
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "embedding_batches.id",
            name="fk_ingestion_failures_batch_id_embedding_batches",
            ondelete="SET NULL",
        )
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
