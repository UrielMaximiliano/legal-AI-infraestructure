"""HTTP contracts for retry and regeneration operations."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.export_service import ExportService
from legal_ai.domain.enums import ExportAttemptStatus, ExportStatus
from legal_ai.main import app
from tests.contract.test_exports_endpoints import _seed_finalized_draft


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_pending_export(client: AsyncClient, draft_id: uuid.UUID):
    key = f"phase12-create-{uuid.uuid4().hex}"
    response = await client.post(
        f"/api/v1/drafts/{draft_id}/exports",
        json={"draft_version": 3, "format": "PDF", "exported_by": "Editor"},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 202
    return response, key


@pytest.mark.contract
@pytest.mark.asyncio
async def test_retry_reuses_failed_export_and_creates_attempt(monkeypatch, client):
    async def no_background_processing(context) -> None:
        return None

    monkeypatch.setattr(ExportService, "process_operation", no_background_processing)
    draft_id = await _seed_finalized_draft(client)
    created, key = await _create_pending_export(client, draft_id)
    export_id = uuid.UUID(created.json()["id"])
    async with UnitOfWork() as uow:
        export = await uow.document_exports.get_by_id(export_id)
        attempt = await uow.export_attempts.get_latest(export_id)
        assert export is not None and attempt is not None
        await uow.document_exports.update_status(export_id, ExportStatus.FAILED)
        attempt.status = ExportAttemptStatus.FAILED
        await uow.export_attempts.update(attempt)

    retried = await client.post(
        f"/api/v1/exports/{export_id}/retry",
        json={"exported_by": "Editor"},
        headers={"Idempotency-Key": key},
    )
    assert retried.status_code == 202
    assert retried.json()["id"] == str(export_id)
    attempts = await client.get(f"/api/v1/exports/{export_id}/attempts")
    assert attempts.status_code == 200
    assert attempts.json()["total"] == 2
    assert attempts.json()["items"][0]["status"] == "PROCESSING"

    active = await client.post(
        f"/api/v1/exports/{export_id}/retry",
        json={"exported_by": "Editor"},
        headers={"Idempotency-Key": key},
    )
    assert active.status_code == 409
    assert active.json()["error_code"] == "EXPORT_IN_PROGRESS"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_regenerate_creates_child_from_generated_metadata(monkeypatch, client):
    async def no_background_processing(context) -> None:
        return None

    monkeypatch.setattr(ExportService, "process_operation", no_background_processing)
    draft_id = await _seed_finalized_draft(client)
    created, _ = await _create_pending_export(client, draft_id)
    source_id = uuid.UUID(created.json()["id"])
    async with UnitOfWork() as uow:
        await uow.document_exports.update_status(
            source_id,
            ExportStatus.GENERATED,
            content_sha256="d" * 64,
        )

    regenerated = await client.post(
        f"/api/v1/exports/{source_id}/regenerate",
        json={"expected_version": 1, "exported_by": "Editor"},
        headers={"Idempotency-Key": f"phase13-regenerate-{uuid.uuid4().hex}"},
    )
    assert regenerated.status_code == 202
    body = regenerated.json()
    assert body["parent_export_id"] == str(source_id)
    assert body["export_version"] == 2
    assert body["status"] == "GENERATING"
