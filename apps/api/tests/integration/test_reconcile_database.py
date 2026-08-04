"""Database-shaped retention scenarios for reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from legal_ai.application.reconcile_service import ReconcileService
from legal_ai.domain.enums import ExportAttemptStatus, ExportFormat, ExportStatus
from legal_ai.domain.export_attempt import ExportAttempt
from tests.unit.test_retry_regeneration_reconcile import _draft, _review, _Uow


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconcile_deletes_only_old_non_latest_failed_attempt(tmp_path) -> None:
    draft = _draft()
    review = _review(draft)
    uow = _Uow(draft, review)
    now = datetime.now(UTC)
    export = await _new_export(uow, draft, review)
    old = ExportAttempt(
        id=uuid4(),
        export_id=export.id,
        draft_id=draft.id,
        format=ExportFormat.PDF,
        idempotency_key="database-key-0001",
        request_hash="a" * 64,
        attempt_number=1,
        status=ExportAttemptStatus.FAILED,
        request_id="request-1",
        exported_by="Admin",
        created_at=now - timedelta(days=181),
        updated_at=now - timedelta(days=181),
    )
    latest = ExportAttempt(
        id=uuid4(),
        export_id=export.id,
        draft_id=draft.id,
        format=ExportFormat.PDF,
        idempotency_key="database-key-0001",
        request_hash="a" * 64,
        attempt_number=2,
        status=ExportAttemptStatus.FAILED,
        request_id="request-2",
        exported_by="Admin",
        created_at=now,
        updated_at=now,
    )
    await uow.export_attempts.create(old)
    await uow.export_attempts.create(latest)
    service = ReconcileService(uow, storage=_EmptyStorage(tmp_path), now=now)
    result = await service.reconcile(actor="Admin", execute=True)
    assert result["deleted"] == 1
    assert old.id not in uow.export_attempts.items
    assert latest.id in uow.export_attempts.items
    assert export.id in uow.document_exports.items


async def _new_export(uow, draft, review):
    from legal_ai.domain.document_export import DocumentExport

    export = DocumentExport(
        id=uuid4(),
        draft_id=draft.id,
        draft_version=draft.version,
        review_id=review.id,
        export_version=1,
        format=ExportFormat.PDF,
        status=ExportStatus.FAILED,
        file_name=f"{draft.id}_v1.pdf",
        source_snapshot_sha256="b" * 64,
        exported_by="Admin",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await uow.document_exports.create(export)
    return export


class _EmptyStorage:
    def __init__(self, tmp_path) -> None:
        self.root = tmp_path

    def health(self) -> bool:
        return True

    def scan_files(self):
        return []
