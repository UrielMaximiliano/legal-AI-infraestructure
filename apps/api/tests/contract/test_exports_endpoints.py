"""HTTP contract coverage for initial exports and metadata reads."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.export_service import ExportService
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus
from legal_ai.main import app
from tests.contract.helpers_003 import seed_case_and_template


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _seed_finalized_draft(client: AsyncClient) -> uuid.UUID:
    case_file_id, template_id = await seed_case_and_template(with_designation=False)
    draft_id = uuid.uuid4()
    now = datetime.now(UTC)
    async with UnitOfWork() as uow:
        await uow.drafts.create(
            Draft(
                id=draft_id,
                template_id=template_id,
                case_file_id=case_file_id,
                title="Export draft",
                content="Approved export content",
                status=DraftStatus.APROBADO,
                version=1,
                generation_number=1,
                context_snapshot={"locale": "es-AR"},
                context_hash="a" * 64,
                created_at=now,
                updated_at=now,
            )
        )
    created = await client.post(
        f"/api/v1/drafts/{draft_id}/reviews",
        json={"draft_version": 1, "expected_version": 1, "opened_by": "Reviewer"},
        headers={"Idempotency-Key": f"export-review-{uuid.uuid4().hex}"},
    )
    review_id = created.json()["id"]
    submitted = await client.post(
        f"/api/v1/reviews/{review_id}/submit",
        json={"expected_version": 1, "submitted_by": "Submitter"},
        headers={"Idempotency-Key": f"export-submit-{uuid.uuid4().hex}"},
    )
    assert submitted.status_code == 200
    approved = await client.post(
        f"/api/v1/reviews/{review_id}/approve",
        json={
            "expected_version": 2,
            "decided_by": "Approver",
            "human_review_confirmed": True,
        },
        headers={"Idempotency-Key": f"export-approve-{uuid.uuid4().hex}"},
    )
    assert approved.status_code == 200
    finalized = await client.post(
        f"/api/v1/drafts/{draft_id}/finalize",
        json={
            "expected_version": 2,
            "finalized_by": "Editor",
            "finalization_notes": "Ready",
        },
    )
    assert finalized.status_code == 200
    return draft_id


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_export_is_202_and_active_replay_is_conflict(
    client, monkeypatch
) -> None:
    draft_id = await _seed_finalized_draft(client)

    async def no_background_processing(context) -> None:
        return None

    monkeypatch.setattr(ExportService, "process_operation", no_background_processing)
    key = f"export-create-{uuid.uuid4().hex}"
    created = await client.post(
        f"/api/v1/drafts/{draft_id}/exports",
        json={"draft_version": 3, "format": "pdf", "exported_by": " Editor "},
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 202
    assert created.json()["status"] == "GENERATING"
    assert created.json()["request_id"]
    assert "storage_path" not in created.json()

    active = await client.post(
        f"/api/v1/drafts/{draft_id}/exports",
        json={"draft_version": 3, "format": "PDF", "exported_by": "Editor"},
        headers={"Idempotency-Key": key},
    )
    assert active.status_code == 409
    assert active.json()["error_code"] == "EXPORT_IN_PROGRESS"

    different_payload = await client.post(
        f"/api/v1/drafts/{draft_id}/exports",
        json={"draft_version": 3, "format": "PDF", "exported_by": "Other"},
        headers={"Idempotency-Key": key},
    )
    assert different_payload.status_code == 409
    assert different_payload.json()["error_code"] == "IDEMPOTENCY_CONFLICT"

    export_id = created.json()["id"]
    metadata = await client.get(f"/api/v1/exports/{export_id}")
    assert metadata.status_code == 200
    assert metadata.json()["request_id"]
    assert "storage_path" not in metadata.json()

    listing = await client.get(
        f"/api/v1/drafts/{draft_id}/exports?page=1&page_size=100&format=pdf"
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["export_version"] == 1

    attempts = await client.get(f"/api/v1/exports/{export_id}/attempts")
    assert attempts.status_code == 200
    assert attempts.json()["total"] == 1
    assert attempts.json()["items"][0]["status"] == "PROCESSING"
    assert attempts.json()["items"][0]["request_hash"]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_export_requires_key_and_rejects_unsupported_format(
    client,
) -> None:
    draft_id = await _seed_finalized_draft(client)
    missing_key = await client.post(
        f"/api/v1/drafts/{draft_id}/exports",
        json={"draft_version": 3, "format": "PDF", "exported_by": "Editor"},
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"

    unsupported = await client.post(
        f"/api/v1/drafts/{draft_id}/exports",
        json={"draft_version": 3, "format": "HTML", "exported_by": "Editor"},
        headers={"Idempotency-Key": f"export-invalid-{uuid.uuid4().hex}"},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error_code"] == "EXPORT_FORMAT_UNSUPPORTED"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_initial_exports_leave_one_active_generation(
    client, monkeypatch
) -> None:
    draft_id = await _seed_finalized_draft(client)

    async def no_background_processing(context) -> None:
        return None

    monkeypatch.setattr(ExportService, "process_operation", no_background_processing)

    async def submit() -> object:
        return await client.post(
            f"/api/v1/drafts/{draft_id}/exports",
            json={"draft_version": 3, "format": "DOCX", "exported_by": "Editor"},
            headers={"Idempotency-Key": f"parallel-{uuid.uuid4().hex}"},
        )

    responses = await asyncio.gather(submit(), submit())
    statuses = sorted(response.status_code for response in responses)
    assert statuses == [202, 409]
