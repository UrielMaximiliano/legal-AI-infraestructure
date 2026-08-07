"""ORM mappings for corpus documents and chunks (incremento 005)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum as PyEnum

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from legal_ai.domain.corpus import CorpusIngestionStatus
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS

from .models import Base


def _enum_type(enum_type: type[PyEnum], *, length: int) -> SAEnum:
    return SAEnum(
        enum_type,
        native_enum=False,
        create_constraint=False,
        length=length,
        values_callable=lambda values: [member.value for member in values],
    )


class CorpusDocumentModel(Base):
    __tablename__ = "corpus_documents"
    __table_args__ = (
        CheckConstraint(
            "provenance_type IN ('AUTOMATED','HUMAN_REVIEWED')",
            name="ck_corpus_documents_provenance",
        ),
        CheckConstraint(
            "review_status IN ('PENDING_REVIEW','REVIEWED','REJECTED')",
            name="ck_corpus_documents_review_status",
        ),
        CheckConstraint(
            "ingestion_status IN ('DISCOVERED','PARSED','NORMALIZED','VALIDATED',"
            "'CHUNKED','EMBEDDING','INDEXED','COMPLETED','FAILED')",
            name="ck_corpus_documents_ingestion_status",
        ),
        CheckConstraint(
            "embedding_status IN ('PENDING','PROCESSING','EMBEDDED','FAILED')",
            name="ck_corpus_documents_embedding_status",
        ),
        CheckConstraint(
            "review_version > 0", name="ck_corpus_documents_review_version_positive"
        ),
        CheckConstraint(
            "(review_status = 'PENDING_REVIEW' AND reviewed_by IS NULL AND "
            "reviewed_at IS NULL) OR (review_status IN ('REVIEWED', 'REJECTED') "
            "AND reviewed_by IS NOT NULL AND btrim(reviewed_by) <> '' AND "
            "reviewed_at IS NOT NULL)",
            name="ck_corpus_documents_review_metadata",
        ),
        CheckConstraint(
            "review_status = 'PENDING_REVIEW' OR provenance_type = 'HUMAN_REVIEWED'",
            name="ck_corpus_documents_review_provenance",
        ),
        CheckConstraint(
            "review_status <> 'REJECTED' OR (review_notes IS NOT NULL AND "
            "btrim(review_notes) <> '')",
            name="ck_corpus_documents_rejection_reason",
        ),
        CheckConstraint(
            "btrim(raw_content) <> ''", name="ck_corpus_documents_raw_not_empty"
        ),
        CheckConstraint(
            "ingestion_status IN ('DISCOVERED', 'FAILED') OR "
            "btrim(normalized_content) <> ''",
            name="ck_corpus_documents_normalized_not_empty",
        ),
        CheckConstraint(
            "active_generation IS NULL OR active_generation > 0",
            name="ck_corpus_documents_active_generation_positive",
        ),
        CheckConstraint(
            "source_url IS NULL OR source_url ~ '^https://'",
            name="ck_corpus_documents_source_url_https",
        ),
        CheckConstraint(
            "raw_content_hash ~ '^[0-9a-f]{64}$'", name="ck_corpus_documents_raw_hash"
        ),
        CheckConstraint(
            "normalized_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_corpus_documents_normalized_hash",
        ),
        Index("ix_corpus_documents_review_status", "review_status"),
        Index(
            "ix_corpus_documents_search_filters",
            "document_type",
            "document_subtype",
            "jurisdiction",
            "review_status",
        ),
        Index("ix_corpus_documents_source_identifier", "source_identifier"),
        Index(
            "ix_corpus_documents_hashes", "raw_content_hash", "normalized_content_hash"
        ),
        Index(
            "uq_corpus_documents_source_external",
            "source_name",
            "external_id",
            unique=True,
            postgresql_where=text("ingestion_status <> 'FAILED'"),
        ),
        Index(
            "uq_corpus_documents_identity_active",
            "source_identifier",
            "raw_content_hash",
            "normalized_content_hash",
            unique=True,
            postgresql_where=text(
                "active_generation IS NOT NULL AND ingestion_status <> 'FAILED'"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    document_subtype: Mapped[str] = mapped_column(String(100), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    organization: Mapped[str | None] = mapped_column(String(200))
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_identifier: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    publication_date: Mapped[date | None] = mapped_column(Date)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    raw_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    provenance_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="AUTOMATED", server_default="AUTOMATED"
    )
    review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING_REVIEW",
        server_default="PENDING_REVIEW",
    )
    review_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)
    ingestion_status: Mapped[CorpusIngestionStatus] = mapped_column(
        _enum_type(CorpusIngestionStatus, length=30),
        nullable=False,
        default=CorpusIngestionStatus.DISCOVERED,
        server_default="DISCOVERED",
    )
    embedding_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", server_default="PENDING"
    )
    created_by_pipeline_version: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    normalization_version: Mapped[str] = mapped_column(String(100), nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(100), nullable=False)
    active_generation: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CorpusChunkModel(Base):
    __tablename__ = "corpus_chunks"
    __table_args__ = (
        CheckConstraint(
            "state IN ('STAGED','EMBEDDING','ACTIVE','FAILED','SUPERSEDED')",
            name="ck_corpus_chunks_state",
        ),
        CheckConstraint("generation > 0", name="ck_corpus_chunks_generation_positive"),
        CheckConstraint(
            "section_index >= 0 AND (paragraph_index IS NULL OR paragraph_index >= 0)",
            name="ck_corpus_chunks_indexes_nonnegative",
        ),
        CheckConstraint(
            "token_count >= 0", name="ck_corpus_chunks_token_count_nonnegative"
        ),
        CheckConstraint("content <> ''", name="ck_corpus_chunks_content_not_empty"),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_corpus_chunks_content_hash"
        ),
        CheckConstraint(
            "embedding_dimensions IS NULL OR embedding_dimensions = "
            f"{EMBEDDING_DIMENSIONS}",
            name="ck_corpus_chunks_embedding_dimensions",
        ),
        CheckConstraint(
            "embedding IS NULL OR (embedding_model IS NOT NULL AND "
            f"embedding_dimensions = {EMBEDDING_DIMENSIONS})",
            name="ck_corpus_chunks_embedding_model",
        ),
        CheckConstraint(
            "state <> 'ACTIVE' OR embedding IS NOT NULL",
            name="ck_corpus_chunks_active_embedding",
        ),
        Index("ix_corpus_chunks_document_generation", "document_id", "generation"),
        Index("ix_corpus_chunks_state", "state"),
        Index(
            "uq_corpus_chunks_document_generation_position",
            "document_id",
            "generation",
            "section_index",
            "paragraph_index",
            unique=True,
        ),
        Index(
            "uq_corpus_chunks_document_generation_hash",
            "document_id",
            "generation",
            "content_hash",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "corpus_documents.id",
            name="fk_corpus_chunks_document_id_corpus_documents",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="STAGED", server_default="STAGED"
    )
    section_type: Mapped[str] = mapped_column(String(40), nullable=False)
    section_index: Mapped[int] = mapped_column(Integer, nullable=False)
    paragraph_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    article_number: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        HALFVEC(EMBEDDING_DIMENSIONS)
    )
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    normalization_version: Mapped[str] = mapped_column(String(100), nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
