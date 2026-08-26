"""Unit tests for write-once finalization semantics."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from legal_ai.application.finalization_service import FinalizationService
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus, ReviewStatus
from legal_ai.domain.errors import (
    ConcurrentModification004Error,
    DraftAlreadyFinalizedError,
    DraftNotApprovedError,
    OpenBlockingCommentsError,
)
from legal_ai.domain.review import DocumentReview


class _Drafts:
    def __init__(self, draft):
        self.draft = draft

    async def get_by_id_for_update(self, draft_id):
        return self.draft if draft_id == self.draft.id else None

    async def update_finalization(
        self,
        draft_id,
        expected_version,
        finalized_by,
        finalized_at,
        finalization_notes,
        final_snapshot,
        final_snapshot_sha256,
        official_number=None,
        issued_on=None,
    ):
        if self.draft.version != expected_version or self.draft.is_finalized():
            return None
        self.draft.finalized_by = finalized_by
        self.draft.finalized_at = finalized_at
        self.draft.finalization_notes = finalization_notes
        self.draft.official_number = official_number
        self.draft.issued_on = issued_on
        self.draft.final_snapshot = final_snapshot
        self.draft.final_snapshot_sha256 = final_snapshot_sha256
        self.draft.version += 1
        return self.draft


class _Reviews:
    def __init__(self, review):
        self.review = review

    async def get_latest_for_draft(self, draft_id):
        return self.review if draft_id == self.review.draft_id else None


class _Comments:
    def __init__(self, count=0):
        self.count = count

    async def count_open_blocking(self, review_id):
        return self.count


class _Events:
    def __init__(self):
        self.items = []

    async def create(self, event):
        self.items.append(event)
        return event


class _Identifiers:
    def __init__(self):
        self.items = []

    async def get_by_draft(self, draft_id):
        return next((item for item in self.items if item.draft_id == draft_id), None)

    async def get_by_identity(self, document_type, number, year):
        return next(
            (
                item
                for item in self.items
                if item.document_type == document_type
                and item.number == number
                and item.year == year
            ),
            None,
        )

    async def create(self, identifier):
        self.items.append(identifier)
        return identifier


class _Templates:
    async def get_by_id(self, template_id):
        return SimpleNamespace(document_type="decreto")


def _uow(status=DraftStatus.APROBADO, blocking=0):
    now = datetime.now(UTC)
    draft = Draft(
        id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        case_file_id=uuid.uuid4(),
        title="Finalizable",
        content="live content",
        status=status,
        version=4,
        generation_number=1,
        context_snapshot={"locale": "es-AR"},
        context_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )
    snapshot = {
        "draft_id": str(draft.id),
        "draft_version": 4,
        "title": draft.title,
        "content": "approved snapshot",
    }
    review = DocumentReview(
        id=uuid.uuid4(),
        draft_id=draft.id,
        draft_version=4,
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
    uow = SimpleNamespace(
        drafts=_Drafts(draft),
        reviews=_Reviews(review),
        review_comments=_Comments(blocking),
        review_events=_Events(),
        official_document_identifiers=_Identifiers(),
        templates=_Templates(),
    )
    return uow, draft


@pytest.mark.unit
async def test_finalization_writes_snapshot_once_and_replays() -> None:
    uow, draft = _uow()
    service = FinalizationService(uow)
    first = await service.finalize(draft.id, 4, " Editor ", " ready ", "req-1")
    assert first.status_code == 200
    assert first.draft.version == 5
    assert first.snapshot["source_text"] == "approved snapshot"
    replay = await service.finalize(draft.id, 4, "Editor", "ready", "req-2")
    assert replay.status_code == 200
    assert replay.sha256 == first.sha256
    assert len(uow.review_events.items) == 1


@pytest.mark.unit
async def test_finalization_reserves_official_number_and_persists_metadata() -> None:
    uow, draft = _uow()
    service = FinalizationService(uow)
    issued_on = date(2026, 8, 26)

    first = await service.finalize(
        draft.id,
        4,
        "Editor",
        None,
        "req-official",
        official_number=123,
        issued_on=issued_on,
    )

    assert first.identifier is not None
    assert first.identifier.document_type == "decreto"
    assert first.identifier.number == 123
    assert draft.official_number == 123
    assert draft.issued_on == issued_on
    assert first.snapshot["document"]["official_number"] == 123

    replay = await service.finalize(
        draft.id,
        4,
        "Editor",
        None,
        "req-official-replay",
        official_number=123,
        issued_on=issued_on,
    )
    assert replay.identifier == first.identifier


@pytest.mark.unit
async def test_finalization_rejects_divergent_payload_stale_version_and_blockers() -> (
    None
):
    uow, draft = _uow()
    service = FinalizationService(uow)
    await service.finalize(draft.id, 4, "Editor", None, "req-1")
    with pytest.raises(DraftAlreadyFinalizedError):
        await service.finalize(draft.id, 4, "Other", None, "req-2")
    with pytest.raises(ConcurrentModification004Error):
        await service.finalize(draft.id, 3, "Editor", None, "req-3")

    blocked_uow, blocked_draft = _uow(blocking=1)
    with pytest.raises(OpenBlockingCommentsError):
        await FinalizationService(blocked_uow).finalize(
            blocked_draft.id, 4, "Editor", None, "req-blocked"
        )


@pytest.mark.unit
async def test_finalization_requires_approved_draft() -> None:
    uow, draft = _uow(status=DraftStatus.EN_REVISION)
    with pytest.raises(DraftNotApprovedError):
        await FinalizationService(uow).finalize(draft.id, 4, "Editor", None, "req-1")
