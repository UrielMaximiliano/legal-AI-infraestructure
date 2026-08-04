"""SQLAlchemy ORM models for the legal-AI system."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class EmployeeModel(Base):
    """Employee table model."""

    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    employee_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(200), nullable=False)
    last_name: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    document_number: Mapped[str] = mapped_column(String(100), nullable=False)
    cuil: Mapped[str | None] = mapped_column(String(11), unique=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    position: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_employees_document",
            "document_type",
            "document_number",
            unique=True,
        ),
        Index("ix_employees_active", "active"),
        Index("ix_employees_department", "department"),
        Index("ix_employees_created_at", "created_at"),
    )


class CaseFileModel(Base):
    """Case files table model."""

    __tablename__ = "case_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_case_files_employee_id", "employee_id"),
        Index("ix_case_files_status", "status"),
        Index("ix_case_files_case_type", "case_type"),
        Index("ix_case_files_opened_at", "opened_at"),
        Index("ix_case_files_created_at", "created_at"),
    )


class CaseStatusHistoryModel(Base):
    """Case status history table model."""

    __tablename__ = "case_status_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_files.id"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_history_case_file_id", "case_file_id"),
        Index("ix_history_changed_at", "changed_at"),
    )


class DocumentTemplateModel(Base):
    """Document templates table model."""

    __tablename__ = "document_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    organ_emisor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    normativa: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "name", "document_type", "version", name="uq_template_name_type_version"
        ),
        Index("ix_templates_document_type", "document_type"),
        Index("ix_templates_is_active", "is_active"),
        Index("ix_templates_name", "name"),
    )


class DesignationDataModel(Base):
    """Designation data table model."""

    __tablename__ = "designation_data"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_files.id"), unique=True, nullable=False
    )
    position_name: Mapped[str] = mapped_column(String(200), nullable=False)
    organizational_unit: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    legal_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    appointing_authority: Mapped[str | None] = mapped_column(String(200), nullable=True)
    salary_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    work_schedule: Mapped[str | None] = mapped_column(String(100), nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_designation_data_case_file_id", "case_file_id"),)


class DocumentDraftModel(Base):
    """Document drafts table model."""

    __tablename__ = "document_drafts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_templates.id"), nullable=False
    )
    case_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_files.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="generado")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    context_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    variables_used: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    parent_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_drafts.id"), nullable=True
    )
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finalized_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finalization_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_snapshot: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    final_snapshot_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    reviews: Mapped[list[DocumentReviewModel]] = relationship(
        "DocumentReviewModel", back_populates="draft"
    )
    exports: Mapped[list[DocumentExportModel]] = relationship(
        "DocumentExportModel", back_populates="draft"
    )

    __table_args__ = (
        Index("ix_drafts_case_file_id", "case_file_id"),
        Index("ix_drafts_status", "status"),
        Index("ix_drafts_parent_draft_id", "parent_draft_id"),
        Index("ix_drafts_template_id", "template_id"),
        Index("ix_drafts_context_hash", "context_hash"),
        CheckConstraint(
            "finalized_by IS NULL OR "
            "char_length(btrim(finalized_by)) BETWEEN 1 AND 100",
            name="ck_drafts_finalized_by_length",
        ),
        CheckConstraint(
            "finalization_notes IS NULL OR char_length(finalization_notes) <= 2000",
            name="ck_drafts_finalization_notes_length",
        ),
        CheckConstraint(
            "final_snapshot_sha256 IS NULL OR "
            "final_snapshot_sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_drafts_final_snapshot_sha256",
        ),
        CheckConstraint(
            "(finalized_at IS NULL AND finalized_by IS NULL "
            "AND final_snapshot IS NULL AND final_snapshot_sha256 IS NULL) OR "
            "(finalized_at IS NOT NULL AND finalized_by IS NOT NULL "
            "AND final_snapshot IS NOT NULL AND final_snapshot_sha256 IS NOT NULL)",
            name="ck_drafts_finalization_complete",
        ),
    )


class DraftTransitionModel(Base):
    """Draft transitions table model."""

    __tablename__ = "draft_transitions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_drafts.id"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_draft_transitions_draft_id", "draft_id"),)


class DocumentReviewModel(Base):
    """Human review bound to one exact draft version."""

    __tablename__ = "document_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_drafts.id"), nullable=False
    )
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    review_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    review_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    opened_by: Mapped[str] = mapped_column(String(100), nullable=False)
    submitted_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    draft: Mapped[DocumentDraftModel] = relationship(
        "DocumentDraftModel", back_populates="reviews"
    )
    comments: Mapped[list[ReviewCommentModel]] = relationship(
        "ReviewCommentModel", back_populates="review"
    )
    exports: Mapped[list[DocumentExportModel]] = relationship(
        "DocumentExportModel", back_populates="review"
    )

    __table_args__ = (
        UniqueConstraint("draft_id", "draft_version", name="uq_review_draft_version"),
        CheckConstraint(
            "draft_version > 0 AND version > 0", name="ck_review_positive_versions"
        ),
        CheckConstraint(
            "status IN ('OPEN','SUBMITTED','CHANGES_REQUESTED','APPROVED','CLOSED')",
            name="ck_review_status",
        ),
        CheckConstraint(
            "char_length(btrim(opened_by)) BETWEEN 1 AND 100",
            name="ck_review_opened_by_length",
        ),
        Index("ix_reviews_draft_id", "draft_id"),
        Index("ix_reviews_status", "status"),
    )


class ReviewOperationRequestModel(Base):
    """Idempotency record scoped by operation, resource and key."""

    __tablename__ = "review_operation_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_payload: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "operation",
            "resource_id",
            "idempotency_key",
            name="uq_review_operation_request",
        ),
        CheckConstraint(
            "status IN ('PROCESSING','SUCCEEDED','FAILED')",
            name="ck_review_operation_status",
        ),
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 16 AND 100",
            name="ck_review_operation_key_length",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-fA-F]{64}$'",
            name="ck_review_operation_request_hash",
        ),
    )


class ReviewCommentModel(Base):
    """Non-destructive review comment or response."""

    __tablename__ = "review_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_reviews.id"), nullable=False
    )
    parent_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_comments.id"), nullable=True
    )
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    author: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    anchor: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    review: Mapped[DocumentReviewModel] = relationship(
        "DocumentReviewModel", back_populates="comments"
    )
    parent: Mapped[ReviewCommentModel | None] = relationship(
        "ReviewCommentModel", remote_side=lambda: [ReviewCommentModel.id]
    )

    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(author)) BETWEEN 1 AND 100",
            name="ck_review_comment_author_length",
        ),
        CheckConstraint(
            "char_length(body) BETWEEN 1 AND 10000", name="ck_review_comment_body"
        ),
        CheckConstraint(
            "severity IN ('INFO','SUGGESTION','WARNING','BLOCKING')",
            name="ck_review_comment_severity",
        ),
        CheckConstraint(
            "status IN ('OPEN','RESOLVED','DISMISSED')",
            name="ck_review_comment_status",
        ),
        Index("ix_review_comments_review_id", "review_id"),
        Index("ix_review_comments_status", "status"),
    )


class DocumentExportModel(Base):
    """Persisted DOCX/PDF metadata; HTML never creates this row."""

    __tablename__ = "document_exports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_drafts.id"), nullable=False
    )
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "document_reviews.id",
            use_alter=True,
            name="fk_exports_review_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    export_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_export_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_exports.id"), nullable=True
    )
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_name: Mapped[str] = mapped_column(String(120), nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    renderer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    renderer_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exported_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    draft: Mapped[DocumentDraftModel] = relationship(
        "DocumentDraftModel", back_populates="exports"
    )
    review: Mapped[DocumentReviewModel] = relationship(
        "DocumentReviewModel", back_populates="exports"
    )
    attempts: Mapped[list[ExportAttemptModel]] = relationship(
        "ExportAttemptModel", back_populates="export"
    )

    __table_args__ = (
        UniqueConstraint(
            "draft_id",
            "format",
            "export_version",
            name="uq_export_draft_format_version",
        ),
        CheckConstraint(
            "draft_version > 0 AND export_version > 0",
            name="ck_export_positive_versions",
        ),
        CheckConstraint("format IN ('DOCX','PDF')", name="ck_export_format"),
        CheckConstraint(
            "status IN ('PENDING','GENERATING','GENERATED','FAILED','SUPERSEDED')",
            name="ck_export_status",
        ),
        CheckConstraint(
            "char_length(file_name) BETWEEN 1 AND 120",
            name="ck_export_file_name_length",
        ),
        CheckConstraint(
            "storage_path IS NULL OR char_length(storage_path) <= 500",
            name="ck_export_storage_path_length",
        ),
        CheckConstraint(
            "source_snapshot_sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_export_source_hash",
        ),
        CheckConstraint(
            "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_export_content_hash",
        ),
        Index("ix_exports_draft_format_status", "draft_id", "format", "status"),
        Index("ix_exports_parent_export_id", "parent_export_id"),
        Index(
            "ix_exports_draft_created",
            "draft_id",
            "created_at",
            "id",
        ),
        Index(
            "uq_exports_active_generation",
            "draft_id",
            "format",
            unique=True,
            postgresql_where=(status.in_(["PENDING", "GENERATING"])),
        ),
    )


class ExportAttemptModel(Base):
    """Every processing attempt, including failed retries."""

    __tablename__ = "export_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    export_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_exports.id"), nullable=False
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_drafts.id"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    exported_by: Mapped[str] = mapped_column(String(100), nullable=False)

    export: Mapped[DocumentExportModel] = relationship(
        "DocumentExportModel", back_populates="attempts"
    )

    __table_args__ = (
        UniqueConstraint(
            "export_id", "attempt_number", name="uq_export_attempt_number"
        ),
        CheckConstraint("format IN ('DOCX','PDF')", name="ck_export_attempt_format"),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','SUCCEEDED','FAILED')",
            name="ck_export_attempt_status",
        ),
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 16 AND 100",
            name="ck_export_attempt_key_length",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-fA-F]{64}$'",
            name="ck_export_attempt_request_hash",
        ),
        CheckConstraint("attempt_number > 0", name="ck_export_attempt_positive_number"),
        Index(
            "uq_export_attempt_active_actor_key",
            "exported_by",
            "idempotency_key",
            unique=True,
            postgresql_where=(status.in_(["PENDING", "PROCESSING"])),
        ),
        Index(
            "ix_export_attempts_draft_format_created",
            "draft_id",
            "format",
            "created_at",
            "id",
        ),
        Index("ix_export_attempts_status", "status"),
        Index(
            "ix_export_attempts_actor_key_created",
            "exported_by",
            "idempotency_key",
            "created_at",
        ),
    )


class ReviewEventModel(Base):
    """Append-only audit event across reviews, drafts and exports."""

    __tablename__ = "review_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_reviews.id"), nullable=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_drafts.id"), nullable=True
    )
    export_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_exports.id"), nullable=True
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "export_attempts.id",
            name="fk_review_events_attempt_id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    draft_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_review_events_review_created", "review_id", "created_at", "id"),
        Index(
            "ix_review_events_resource_created",
            "resource_type",
            "resource_id",
            "created_at",
            "id",
        ),
        Index(
            "uq_review_events_reconciliation_run",
            "run_id",
            unique=True,
            postgresql_where=(
                (event_type == "RECONCILIATION_RUN") & run_id.is_not(None)
            ),
        ),
    )


class GenerationAttemptModel(Base):
    """Generation attempts table model."""

    __tablename__ = "generation_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_files.id"), nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_templates.id"), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_progress"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_generation_attempts_idempotency_key",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_generation_attempts_case_file_id", "case_file_id"),
        Index("ix_generation_attempts_status", "status"),
    )
