"""Deterministic synthetic factories for 004 integration tests."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from legal_ai.domain.document_export import DocumentExport
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import (
    DraftStatus,
    ExportAttemptStatus,
    ExportFormat,
    ExportStatus,
    ReviewStatus,
)
from legal_ai.domain.export_attempt import ExportAttempt
from legal_ai.domain.review import DocumentReview


def synthetic_snapshot(draft_id: uuid.UUID, version: int = 1) -> dict[str, object]:
    """Create a stable, non-PII review/finalization snapshot."""
    return {
        "schema_version": 1,
        "draft_id": str(draft_id),
        "source_draft_version": version,
        "document": {"title": "Synthetic document", "locale": "es-AR"},
        "source_text": "Synthetic test content",
    }


def approved_draft() -> Draft:
    """Create an approved synthetic draft."""
    now = datetime.now(UTC)
    draft_id = uuid.uuid4()
    return Draft(
        id=draft_id,
        template_id=uuid.uuid4(),
        case_file_id=uuid.uuid4(),
        title="Synthetic draft",
        content="Synthetic approved content",
        status=DraftStatus.APROBADO,
        version=1,
        generation_number=1,
        context_snapshot={"metadata": {"synthetic": True}},
        context_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )


def review_for(draft: Draft) -> DocumentReview:
    """Create an approved and closed review for a draft."""
    now = datetime.now(UTC)
    snapshot = synthetic_snapshot(draft.id, draft.version)
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DocumentReview(
        id=uuid.uuid4(),
        draft_id=draft.id,
        draft_version=draft.version,
        review_snapshot=snapshot,
        review_snapshot_sha256=digest,
        status=ReviewStatus.CLOSED,
        opened_by="synthetic-reviewer",
        decided_by="synthetic-reviewer",
        version=2,
        opened_at=now,
        decided_at=now,
        closed_at=now,
        created_at=now,
        updated_at=now,
    )


def export_for(draft: Draft, review: DocumentReview) -> DocumentExport:
    """Create metadata for a synthetic DOCX export."""
    now = datetime.now(UTC)
    return DocumentExport(
        id=uuid.uuid4(),
        draft_id=draft.id,
        draft_version=draft.version,
        review_id=review.id,
        export_version=1,
        format=ExportFormat.DOCX,
        status=ExportStatus.PENDING,
        file_name=f"{draft.id}_v1.docx".lower(),
        source_snapshot_sha256=review.review_snapshot_sha256,
        exported_by="synthetic-exporter",
        created_at=now,
        updated_at=now,
    )


def attempt_for(export: DocumentExport) -> ExportAttempt:
    """Create a synthetic first export attempt."""
    now = datetime.now(UTC)
    return ExportAttempt(
        id=uuid.uuid4(),
        export_id=export.id,
        draft_id=export.draft_id,
        format=export.format,
        idempotency_key="synthetic-key-0001",
        request_hash="b" * 64,
        attempt_number=1,
        status=ExportAttemptStatus.PENDING,
        request_id="synthetic-request",
        exported_by=export.exported_by,
        created_at=now,
        updated_at=now,
    )
