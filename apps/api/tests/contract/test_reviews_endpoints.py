"""Contract tests for the 004 human-review endpoints."""

from __future__ import annotations

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
                title="Review contract draft",
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


@pytest.mark.contract
async def test_review_endpoints_cover_lifecycle_replay_and_audit(client) -> None:
    draft_id = await _seed_approved_draft()
    create_body = {"draft_version": 1, "expected_version": 1, "opened_by": "Reviewer"}
    key = f"review-api-{uuid.uuid4().hex}"
    created = await client.post(
        f"/api/v1/drafts/{draft_id}/reviews",
        json=create_body,
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 201
    review_id = created.json()["id"]
    assert created.headers.get("x-request-id")

    replay = await client.post(
        f"/api/v1/drafts/{draft_id}/reviews",
        json=create_body,
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == review_id

    current = await client.get(f"/api/v1/drafts/{draft_id}/reviews/current")
    assert current.status_code == 200
    comment = await client.post(
        f"/api/v1/reviews/{review_id}/comments",
        json={
            "expected_version": 1,
            "draft_version": 1,
            "author": "Reviewer",
            "severity": "INFO",
            "body": "Check wording",
        },
        headers={"Idempotency-Key": f"comment-api-{uuid.uuid4().hex}"},
    )
    assert comment.status_code == 201

    submitted = await client.post(
        f"/api/v1/reviews/{review_id}/submit",
        json={"expected_version": 1, "submitted_by": "Submitter"},
        headers={"Idempotency-Key": f"submit-api-{uuid.uuid4().hex}"},
    )
    assert submitted.status_code == 200
    approved = await client.post(
        f"/api/v1/reviews/{review_id}/approve",
        json={
            "expected_version": 2,
            "decided_by": "Approver",
            "human_review_confirmed": True,
        },
        headers={"Idempotency-Key": f"approve-api-{uuid.uuid4().hex}"},
    )
    assert approved.status_code == 200
    history = await client.get(
        f"/api/v1/reviews/{review_id}/history?page=1&page_size=100"
    )
    assert history.status_code == 200
    assert history.json()["total"] >= 4


@pytest.mark.contract
async def test_review_contract_rejects_missing_key_and_reports_sanitized_not_found(
    client,
) -> None:
    draft_id = uuid.uuid4()
    missing = await client.post(
        f"/api/v1/drafts/{draft_id}/reviews",
        json={"draft_version": 1, "expected_version": 1, "opened_by": "Reviewer"},
    )
    assert missing.status_code == 400
    assert missing.json()["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert missing.json()["error"]["request_id"]
    assert "traceback" not in str(missing.json()).lower()

    not_found = await client.get(f"/api/v1/drafts/{draft_id}/reviews/current")
    assert not_found.status_code == 404
    assert not_found.json()["error_code"] == "DRAFT_NOT_FOUND"
    assert not_found.json()["error"]["request_id"]
