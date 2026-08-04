"""Transaction boundaries for review operations in 004."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.finalization_service import FinalizationService
from legal_ai.application.preview_service import PreviewService
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus, ReviewOperationStatus, ReviewStatus
from legal_ai.domain.review import DocumentReview, ReviewOperationRequest
from tests.contract.helpers_003 import seed_case_and_template


async def _seed_finalizable() -> uuid.UUID:
    case_file_id, template_id = await seed_case_and_template(with_designation=False)
    now = datetime.now(UTC)
    draft = Draft(
        id=uuid.uuid4(),
        template_id=template_id,
        case_file_id=case_file_id,
        title="UoW finalization",
        content="Approved snapshot",
        status=DraftStatus.APROBADO,
        version=1,
        generation_number=1,
        context_snapshot={"locale": "es-AR"},
        context_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )
    snapshot = {
        "draft_id": str(draft.id),
        "draft_version": 1,
        "title": draft.title,
        "content": draft.content,
    }
    review = DocumentReview(
        id=uuid.uuid4(),
        draft_id=draft.id,
        draft_version=1,
        review_snapshot=snapshot,
        review_snapshot_sha256="b" * 64,
        status=ReviewStatus.CLOSED,
        opened_by="Reviewer",
        version=2,
        opened_at=now,
        created_at=now,
        updated_at=now,
        decided_at=now,
        closed_at=now,
    )
    async with UnitOfWork() as uow:
        await uow.drafts.create(draft)
        await uow.reviews.create(review)
    return draft.id


@pytest.mark.integration
async def test_review_claim_commits_and_rollback_discards_it() -> None:
    request = ReviewOperationRequest(
        id=uuid.uuid4(),
        operation="TEST_REVIEW",
        resource_id=uuid.uuid4(),
        idempotency_key=f"review-uow-{uuid.uuid4().hex}",
        request_hash="a" * 64,
        status=ReviewOperationStatus.PROCESSING,
        expires_at=datetime.now(UTC),
        request_id="req-uow",
        created_at=datetime.now(UTC),
    )
    async with UnitOfWork() as uow:
        await uow.review_operations.create(request)

    async with UnitOfWork() as uow:
        loaded = await uow.review_operations.get(
            request.operation, request.resource_id, request.idempotency_key
        )
        assert loaded is not None
        await uow.rollback()

    async with UnitOfWork() as uow:
        assert (
            await uow.review_operations.get(
                request.operation, request.resource_id, request.idempotency_key
            )
            is not None
        )

    rolled_back = ReviewOperationRequest(
        id=uuid.uuid4(),
        operation="TEST_REVIEW",
        resource_id=uuid.uuid4(),
        idempotency_key=f"review-uow-{uuid.uuid4().hex}",
        request_hash="b" * 64,
        status=ReviewOperationStatus.PROCESSING,
        expires_at=datetime.now(UTC),
        request_id="req-rollback",
        created_at=datetime.now(UTC),
    )
    with pytest.raises(RuntimeError):
        async with UnitOfWork() as uow:
            await uow.review_operations.create(rolled_back)
            raise RuntimeError("rollback")
    async with UnitOfWork() as uow:
        assert (
            await uow.review_operations.get(
                rolled_back.operation,
                rolled_back.resource_id,
                rolled_back.idempotency_key,
            )
            is None
        )


@pytest.mark.integration
async def test_finalization_snapshot_hash_and_rollback_are_atomic() -> None:
    draft_id = await _seed_finalizable()
    async with UnitOfWork() as uow:
        result = await FinalizationService(uow).finalize(
            draft_id, 1, "Editor", "ready", "request-finalize"
        )
    assert result.draft.version == 2
    async with UnitOfWork() as uow:
        saved = await uow.drafts.get_by_id(draft_id)
        assert saved is not None
        assert saved.final_snapshot_sha256 == result.sha256
        assert saved.finalized_at is not None

    rollback_id = await _seed_finalizable()
    with pytest.raises(RuntimeError):
        async with UnitOfWork() as uow:

            async def fail_event(event):
                raise RuntimeError("event failure")

            uow.review_events.create = fail_event
            await FinalizationService(uow).finalize(
                rollback_id, 1, "Editor", None, "request-rollback"
            )
    async with UnitOfWork() as uow:
        rolled_back = await uow.drafts.get_by_id(rollback_id)
        assert rolled_back is not None
        assert rolled_back.version == 1
        assert rolled_back.final_snapshot is None


@pytest.mark.integration
async def test_preview_is_read_only_and_does_not_create_export_rows() -> None:
    draft_id = await _seed_finalizable()
    async with UnitOfWork() as uow:
        result = await PreviewService(uow).preview(draft_id, 1)
        draft = await uow.drafts.get_by_id(draft_id)
        exports, total = await uow.document_exports.list_by_draft(draft_id, 0, 100)
    assert result.html
    assert draft is not None
    assert draft.version == 1
    assert draft.status == DraftStatus.APROBADO
    assert total == 0
    assert exports == []
