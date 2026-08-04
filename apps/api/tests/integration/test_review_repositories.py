"""PostgreSQL integration tests for 004 review repositories."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import pytest

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.case_file import CaseFile
from legal_ai.domain.draft import Draft
from legal_ai.domain.employee import Employee
from legal_ai.domain.enums import (
    CaseStatus,
    CaseType,
    CommentSeverity,
    CommentStatus,
    DocumentType,
    DraftStatus,
    ReviewStatus,
    TemplateDocumentType,
)
from legal_ai.domain.review import DocumentReview
from legal_ai.domain.review_comment import ReviewComment
from legal_ai.domain.review_event import ReviewEvent
from legal_ai.domain.template import Template


async def _seed() -> tuple[Draft, DocumentReview]:
    now = datetime.now(UTC)
    employee = Employee(
        id=uuid.uuid4(),
        employee_number=f"LEG-{uuid.uuid4().hex[:10]}",
        first_name="Review",
        last_name="Integration",
        document_type=DocumentType.DNI,
        document_number=str(uuid.uuid4().int)[:8],
        created_at=now,
        updated_at=now,
    )
    case_file = CaseFile(
        id=uuid.uuid4(),
        case_number=f"EXP-{uuid.uuid4().hex[:10]}",
        employee_id=employee.id,
        title="Review integration",
        case_type=CaseType.OTRO,
        status=CaseStatus.DRAFT,
        opened_at=now,
        created_at=now,
        updated_at=now,
    )
    template = Template(
        id=uuid.uuid4(),
        name=f"Review template {uuid.uuid4().hex[:8]}",
        document_type=TemplateDocumentType.RESOLUCION,
        version=1,
        body_template="body",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    draft = Draft(
        id=uuid.uuid4(),
        template_id=template.id,
        case_file_id=case_file.id,
        title="Review draft",
        content="Content",
        status=DraftStatus.APROBADO,
        version=1,
        generation_number=1,
        context_snapshot={"locale": "es-AR"},
        context_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )
    snapshot = {"draft_id": str(draft.id), "draft_version": 1, "content": draft.content}
    review = DocumentReview(
        id=uuid.uuid4(),
        draft_id=draft.id,
        draft_version=1,
        review_snapshot=snapshot,
        review_snapshot_sha256=hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        status=ReviewStatus.OPEN,
        opened_by="Reviewer",
        version=1,
        opened_at=now,
        created_at=now,
        updated_at=now,
    )
    async with UnitOfWork() as uow:
        await uow.employees.create(employee)
        await uow.case_files.create(case_file)
        await uow.templates.create(template)
        await uow.drafts.create(draft)
        await uow.reviews.create(review)
    return draft, review


@pytest.mark.integration
async def test_review_repositories_preserve_snapshot_anchors_and_events() -> None:
    draft, review = await _seed()
    now = datetime.now(UTC)
    comment = ReviewComment(
        id=uuid.uuid4(),
        review_id=review.id,
        draft_version=review.draft_version,
        author="Reviewer",
        severity=CommentSeverity.INFO,
        status=CommentStatus.OPEN,
        body="Check",
        version=1,
        created_at=now,
        updated_at=now,
        anchor={"draft_version": review.draft_version},
    )
    event = ReviewEvent(
        id=uuid.uuid4(),
        review_id=review.id,
        draft_id=draft.id,
        resource_type="REVIEW",
        resource_id=str(review.id),
        event_type="COMMENT_ADDED",
        actor="Reviewer",
        request_id="req-review",
        draft_version=1,
        summary={"comment_id": str(comment.id)},
        created_at=now,
    )
    async with UnitOfWork() as uow:
        await uow.review_comments.create(comment)
        await uow.review_events.create(event)
        assert (
            await uow.reviews.get_current(draft.id, 1)
        ).review_snapshot == review.review_snapshot
        assert (await uow.review_comments.list_by_review(review.id, 0, 10))[1] == 1
        assert (await uow.review_events.list_by_review(review.id, 0, 10))[1] == 1

    async with UnitOfWork() as uow:
        loaded = await uow.reviews.get_by_id(review.id)
        assert loaded is not None
        loaded.status = ReviewStatus.SUBMITTED
        updated = await uow.reviews.update(loaded, expected_version=99)
        assert updated is None
