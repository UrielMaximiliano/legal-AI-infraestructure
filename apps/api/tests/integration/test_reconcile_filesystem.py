"""Filesystem scenarios for manual export reconciliation."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage
from legal_ai.application.reconcile_service import ReconcileService
from tests.unit.test_retry_regeneration_reconcile import _draft, _review, _Uow


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconcile_temp_file_dry_run_then_execute(tmp_path) -> None:
    draft = _draft()
    storage = LocalArtifactStorage(tmp_path)
    relative = storage.build_relative_path(
        draft.case_file_id, draft.id, "PDF", 1, f"{draft.id}_v1.pdf"
    )
    temporary = storage.create_temp(relative)
    temporary.write_bytes(b"temporary")
    old = datetime.now(UTC) - timedelta(hours=25)
    os.utime(temporary, (old.timestamp(), old.timestamp()))
    uow = _Uow(draft, _review(draft))

    dry_run = await ReconcileService(uow, storage=storage).reconcile(
        actor="Admin", run_id=None
    )
    assert dry_run["mode"] == "dry-run"
    assert storage.exists(relative) is False
    assert temporary.exists()

    executed = await ReconcileService(uow, storage=storage).reconcile(
        actor="Admin", execute=True
    )
    assert executed["deleted"] == 1
    assert not temporary.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconcile_orphan_requires_first_detection_plus_seven_days(
    tmp_path,
) -> None:
    draft = _draft()
    storage = LocalArtifactStorage(tmp_path)
    relative = storage.build_relative_path(
        draft.case_file_id, draft.id, "PDF", 2, f"{draft.id}_v2.pdf"
    )
    orphan = storage.create_temp(
        storage.build_relative_path(
            draft.case_file_id, draft.id, "PDF", 3, f"{draft.id}_v3.pdf"
        )
    )
    orphan.write_bytes(b"orphan")
    orphan_final = storage.resolve_relative(relative)
    orphan_final.parent.mkdir(parents=True, exist_ok=True)
    orphan.replace(orphan_final)
    uow = _Uow(draft, _review(draft))
    first = await ReconcileService(uow, storage=storage).reconcile(actor="Admin")
    assert first["deleted"] == 0
    detection = next(
        event
        for event in uow.review_events.items
        if event.event_type == "ORPHAN_DETECTED"
    )
    detection.created_at = datetime.now(UTC) - timedelta(days=8)
    executed = await ReconcileService(uow, storage=storage).reconcile(
        actor="Admin", execute=True
    )
    assert executed["deleted"] == 1
    assert not orphan_final.exists()
