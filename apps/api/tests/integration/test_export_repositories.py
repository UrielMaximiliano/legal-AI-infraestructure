"""Repository constraints and stable export ordering for phase 10."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.enums import ExportAttemptStatus, ExportStatus
from legal_ai.domain.export_attempt import ExportAttempt
from legal_ai.main import app
from tests.contract.test_exports_endpoints import _seed_finalized_draft


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.integration
@pytest.mark.asyncio
async def test_export_repository_version_and_active_constraints(
    client: AsyncClient, monkeypatch
) -> None:
    draft_id = await _seed_finalized_draft(client)

    async def no_background_processing(context) -> None:
        return None

    from legal_ai.application.export_service import ExportService

    monkeypatch.setattr(ExportService, "process_operation", no_background_processing)
    response = await client.post(
        f"/api/v1/drafts/{draft_id}/exports",
        json={"draft_version": 3, "format": "PDF", "exported_by": "Editor"},
        headers={"Idempotency-Key": f"repo-key-{uuid.uuid4().hex}"},
    )
    assert response.status_code == 202
    export_id = uuid.UUID(response.json()["id"])

    async with UnitOfWork() as uow:
        exports, total = await uow.document_exports.list_by_draft(
            draft_id,
            0,
            100,
            draft_version=3,
            export_version=1,
            status=ExportStatus.GENERATING,
        )
    assert total == 1 and exports[0].id == export_id

    async with UnitOfWork() as uow:
        export = await uow.document_exports.get_by_id(export_id)
        assert export is not None
        attempt = await uow.export_attempts.get_latest(export_id)
        assert attempt is not None
        duplicate_attempt = ExportAttempt(
            id=uuid.uuid4(),
            export_id=export.id,
            draft_id=export.draft_id,
            format=export.format,
            idempotency_key=attempt.idempotency_key,
            request_hash=attempt.request_hash,
            attempt_number=2,
            status=ExportAttemptStatus.PROCESSING,
            request_id="duplicate",
            exported_by=attempt.exported_by,
            created_at=attempt.created_at,
            started_at=attempt.started_at,
        )
        try:
            with pytest.raises(IntegrityError):
                await uow.export_attempts.create(duplicate_attempt)
        finally:
            await uow.rollback()
