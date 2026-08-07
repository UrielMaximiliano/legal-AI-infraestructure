"""Contract tests for the write-once finalization endpoint."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus
from legal_ai.main import app
from tests.contract.helpers_003 import seed_case_and_template


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _seed_approved_draft() -> uuid.UUID:
    case_file_id, template_id = await seed_case_and_template(with_designation=False)
    draft_id = uuid.uuid4()
    now = datetime.now(UTC)
    async with UnitOfWork() as uow:
        await uow.drafts.create(
            Draft(
                id=draft_id,
                template_id=template_id,
                case_file_id=case_file_id,
                title="Finalization draft",
                content="Approved content",
                status=DraftStatus.APROBADO,
                version=1,
                generation_number=1,
                context_snapshot={"locale": "es-AR"},
                context_hash="a" * 64,
                created_at=now,
                updated_at=now,
            )
        )
    return draft_id


async def _seed_closed_review(client: AsyncClient) -> uuid.UUID:
    draft_id = await _seed_approved_draft()
    created = await client.post(
        f"/api/v1/drafts/{draft_id}/reviews",
        json={"draft_version": 1, "expected_version": 1, "opened_by": "Reviewer"},
        headers={"Idempotency-Key": f"final-review-{uuid.uuid4().hex}"},
    )
    review_id = uuid.UUID(created.json()["id"])
    submitted = await client.post(
        f"/api/v1/reviews/{review_id}/submit",
        json={"expected_version": 1, "submitted_by": "Submitter"},
        headers={"Idempotency-Key": f"final-submit-{uuid.uuid4().hex}"},
    )
    assert submitted.status_code == 200
    approved = await client.post(
        f"/api/v1/reviews/{review_id}/approve",
        json={
            "expected_version": 2,
            "decided_by": "Approver",
            "human_review_confirmed": True,
        },
        headers={"Idempotency-Key": f"final-approve-{uuid.uuid4().hex}"},
    )
    assert approved.status_code == 200
    return draft_id


@pytest.mark.contract
async def test_finalize_is_write_once_and_blocks_legacy_mutations(client) -> None:
    draft_id = await _seed_closed_review(client)
    body = {
        "expected_version": 2,
        "finalized_by": " Editor ",
        "finalization_notes": " Ready ",
    }
    first = await client.post(f"/api/v1/drafts/{draft_id}/finalize", json=body)
    assert first.status_code == 200
    payload = first.json()
    assert payload["draft_version"] == 3
    assert payload["finalized_by"] == "Editor"
    assert payload["finalization_notes"] == "Ready"
    assert payload["final_snapshot_sha256"]

    replay = await client.post(f"/api/v1/drafts/{draft_id}/finalize", json=body)
    assert replay.status_code == 200
    assert replay.json()["final_snapshot_sha256"] == payload["final_snapshot_sha256"]

    divergent = await client.post(
        f"/api/v1/drafts/{draft_id}/finalize",
        json={**body, "finalized_by": "Other"},
    )
    assert divergent.status_code == 409
    assert divergent.json()["error_code"] == "DRAFT_ALREADY_FINALIZED"

    stale = await client.post(
        f"/api/v1/drafts/{draft_id}/finalize",
        json={**body, "expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "CONCURRENT_MODIFICATION"

    edit = await client.patch(
        f"/api/v1/drafts/{draft_id}/content",
        json={"content": "blocked", "expected_version": 3},
    )
    assert edit.status_code == 409
    assert edit.json()["error_code"] == "DRAFT_READ_ONLY"


@pytest.mark.contract
async def test_preview_before_finalization_is_html_and_has_no_cache(client) -> None:
    draft_id = await _seed_approved_draft()
    first = await client.get(f"/api/v1/drafts/{draft_id}/preview?draft_version=1")
    assert first.status_code == 200
    assert first.headers["content-type"] == "text/html; charset=utf-8"
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["etag"].startswith('"sha256:')
    assert "Approved content" in first.text
    expected = hashlib.sha256(first.content).hexdigest()
    assert first.headers["etag"] == f'"sha256:{expected}"'


@pytest.mark.contract
async def test_preview_uses_only_final_snapshot_after_finalization(client) -> None:
    draft_id = await _seed_closed_review(client)
    finalized = await client.post(
        f"/api/v1/drafts/{draft_id}/finalize",
        json={
            "expected_version": 2,
            "finalized_by": "Editor",
            "finalization_notes": "Ready",
        },
    )
    assert finalized.status_code == 200
    response = await client.get(f"/api/v1/drafts/{draft_id}/preview?draft_version=3")
    assert response.status_code == 200
    assert "Approved content" in response.text
    assert "final_snapshot" not in response.text


@pytest.mark.contract
async def test_preview_requires_current_version_and_approved_draft(client) -> None:
    draft_id = await _seed_approved_draft()
    stale = await client.get(f"/api/v1/drafts/{draft_id}/preview?draft_version=2")
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "CONCURRENT_MODIFICATION"
    missing = await client.get(f"/api/v1/drafts/{draft_id}/preview")
    assert missing.status_code == 422

    case_file_id, template_id = await seed_case_and_template(with_designation=False)
    not_approved_id = uuid.uuid4()
    now = datetime.now(UTC)
    async with UnitOfWork() as uow:
        await uow.drafts.create(
            Draft(
                id=not_approved_id,
                template_id=template_id,
                case_file_id=case_file_id,
                title="Not approved",
                content="Draft",
                status=DraftStatus.GENERADO,
                version=1,
                generation_number=1,
                context_snapshot={"locale": "es-AR"},
                context_hash="a" * 64,
                created_at=now,
                updated_at=now,
            )
        )
    rejected = await client.get(
        f"/api/v1/drafts/{not_approved_id}/preview?draft_version=1"
    )
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "DRAFT_NOT_APPROVED"


@pytest.mark.integration
async def test_preview_has_no_database_or_filesystem_side_effects(
    client, tmp_path
) -> None:
    draft_id = await _seed_approved_draft()
    before = await client.get(f"/api/v1/drafts/{draft_id}/preview?draft_version=1")
    assert before.status_code == 200
    async with UnitOfWork() as uow:
        draft = await uow.drafts.get_by_id(draft_id)
        exports, total = await uow.document_exports.list_by_draft(draft_id, 0, 100)
    assert draft is not None and draft.version == 1
    assert total == 0 and exports == []
    assert list(tmp_path.iterdir()) == []
