"""Unit coverage for the phase 10 export orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage
from legal_ai.application import export_service as export_service_module
from legal_ai.application.export_service import ExportService
from legal_ai.domain.document_export import DocumentExport
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import (
    DraftStatus,
    ExportAttemptStatus,
    ExportStatus,
    ReviewStatus,
)
from legal_ai.domain.errors import (
    ActiveGenerationExistsError,
    ExportInProgressError,
    GenerationTimeoutError,
)
from legal_ai.domain.export_attempt import ExportAttempt
from legal_ai.domain.review import DocumentReview


def _draft() -> Draft:
    now = datetime.now(UTC)
    draft_id = uuid4()
    return Draft(
        id=draft_id,
        template_id=uuid4(),
        case_file_id=uuid4(),
        title="Synthetic export",
        status=DraftStatus.APROBADO,
        version=3,
        generation_number=1,
        context_snapshot={"locale": "es-AR"},
        context_hash="a" * 64,
        created_at=now,
        updated_at=now,
        content="Approved content",
        finalized_by="Editor",
        finalized_at=now,
        final_snapshot={
            "document": {"title": "Synthetic export", "locale": "es-AR"},
            "source_text": "Approved content",
        },
        final_snapshot_sha256="b" * 64,
    )


def _review(draft: Draft) -> DocumentReview:
    now = datetime.now(UTC)
    return DocumentReview(
        id=uuid4(),
        draft_id=draft.id,
        draft_version=1,
        review_snapshot={"content": "Approved content"},
        review_snapshot_sha256="c" * 64,
        status=ReviewStatus.CLOSED,
        opened_by="Reviewer",
        version=3,
        opened_at=now,
        created_at=now,
        updated_at=now,
        closed_at=now,
    )


class FakeDrafts:
    def __init__(self, draft: Draft) -> None:
        self.draft = draft

    async def get_by_id_for_update(self, draft_id):
        return self.draft if draft_id == self.draft.id else None

    async def get_by_id(self, draft_id):
        return self.draft if draft_id == self.draft.id else None


class FakeReviews:
    def __init__(self, review: DocumentReview) -> None:
        self.review = review

    async def get_latest_for_draft(self, draft_id):
        return self.review if draft_id == self.review.draft_id else None


class FakeExports:
    def __init__(self) -> None:
        self.items: dict[object, DocumentExport] = {}

    async def get_active(self, draft_id, export_format):
        return next(
            (
                item
                for item in self.items.values()
                if item.draft_id == draft_id
                and item.format == export_format
                and item.status in {ExportStatus.PENDING, ExportStatus.GENERATING}
            ),
            None,
        )

    async def next_version(self, draft_id, export_format):
        versions = [
            item.export_version
            for item in self.items.values()
            if item.draft_id == draft_id and item.format == export_format
        ]
        return max(versions, default=0) + 1

    async def create(self, value):
        self.items[value.id] = value
        return value

    async def update_status(self, export_id, status, **values):
        value = self.items[export_id]
        value.status = status
        for name, item in values.items():
            setattr(value, name, item)
        return value

    async def get_by_id(self, export_id):
        return self.items.get(export_id)

    async def get_by_id_for_update(self, export_id):
        return self.items.get(export_id)

    async def mark_previous_generated(self, draft_id, export_format, exclude_id):
        for value in self.items.values():
            if (
                value.draft_id == draft_id
                and value.format == export_format
                and value.id != exclude_id
                and value.status == ExportStatus.GENERATED
            ):
                value.status = ExportStatus.SUPERSEDED


class FakeAttempts:
    def __init__(self) -> None:
        self.items: dict[object, ExportAttempt] = {}

    async def get_latest_by_draft_key(self, draft_id, idempotency_key):
        values = [
            item
            for item in self.items.values()
            if item.draft_id == draft_id and item.idempotency_key == idempotency_key
        ]
        return max(values, key=lambda item: item.created_at, default=None)

    async def create(self, value):
        self.items[value.id] = value
        return value

    async def update(self, value):
        self.items[value.id] = value
        return value

    async def get_by_id(self, attempt_id):
        return self.items.get(attempt_id)


class FakeUow:
    def __init__(self, draft: Draft, review: DocumentReview) -> None:
        self.drafts = FakeDrafts(draft)
        self.reviews = FakeReviews(review)
        self.document_exports = FakeExports()
        self.export_attempts = FakeAttempts()


@pytest.mark.asyncio
async def test_initial_export_claims_tx1_and_replays_same_key() -> None:
    draft = _draft()
    uow = FakeUow(draft, _review(draft))
    service = ExportService(uow)

    first = await service.create_initial(
        draft.id,
        draft.version,
        "pdf",
        " Editor ",
        "export-key-0000001",
        "request-1",
    )

    assert first.status_code == 202
    assert first.export.status == ExportStatus.GENERATING
    assert first.attempt.status == ExportAttemptStatus.PROCESSING
    assert first.processing is not None
    assert len(uow.document_exports.items) == 1
    assert len(uow.export_attempts.items) == 1

    first.export.status = ExportStatus.GENERATED
    first.attempt.status = ExportAttemptStatus.SUCCEEDED

    replay = await service.create_initial(
        draft.id,
        draft.version,
        "PDF",
        "Editor",
        "export-key-0000001",
        "request-2",
    )
    assert replay.status_code == 200
    assert replay.export.id == first.export.id
    assert len(uow.export_attempts.items) == 1


@pytest.mark.asyncio
async def test_active_export_and_active_idempotency_are_conflicts() -> None:
    draft = _draft()
    uow = FakeUow(draft, _review(draft))
    service = ExportService(uow)
    first = await service.create_initial(
        draft.id,
        draft.version,
        "DOCX",
        "Editor",
        "export-key-0000002",
        "request-1",
    )

    with pytest.raises(ExportInProgressError):
        await service.create_initial(
            draft.id,
            draft.version,
            "DOCX",
            "Editor",
            "export-key-0000002",
            "request-2",
        )
    assert first.export.status == ExportStatus.GENERATING

    other_uow = FakeUow(draft, _review(draft))
    other_uow.document_exports.items[first.export.id] = first.export
    other_service = ExportService(other_uow)
    with pytest.raises(ActiveGenerationExistsError):
        await other_service.create_initial(
            draft.id,
            draft.version,
            "DOCX",
            "Editor",
            "export-key-0000003",
            "request-3",
        )


class FakeSupervisor:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def run(self, renderer, input_data, output_path: Path, timeout_seconds: int):
        if self.error:
            raise self.error
        output_path.write_bytes(b"synthetic artifact")
        return output_path


class FakeIntegrity:
    def validate_pdf(self, path, **kwargs):
        return "d" * 64

    def validate_docx(self, path, **kwargs):
        return "d" * 64


class FakeTxUow(FakeUow):
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None


@pytest.mark.asyncio
async def test_process_success_publishes_only_after_tx2(monkeypatch, tmp_path) -> None:
    draft = _draft()
    review = _review(draft)
    create_uow = FakeUow(draft, review)
    created = await ExportService(create_uow).create_initial(
        draft.id,
        draft.version,
        "PDF",
        "Editor",
        "export-key-0000004",
        "request-4",
    )
    tx_uow = FakeTxUow(draft, review)
    tx_uow.document_exports.items[created.export.id] = created.export
    tx_uow.export_attempts.items[created.attempt.id] = created.attempt
    monkeypatch.setattr(export_service_module, "UnitOfWork", lambda: tx_uow)
    storage = LocalArtifactStorage(tmp_path)
    service = ExportService(
        None,
        storage=storage,
        supervisor=FakeSupervisor(),
        integrity=FakeIntegrity(),
    )

    await service.process(created.processing)

    assert storage.exists(created.processing.relative_path)
    assert (
        tx_uow.document_exports.items[created.export.id].status
        == ExportStatus.GENERATED
    )
    assert (
        tx_uow.export_attempts.items[created.attempt.id].status
        == ExportAttemptStatus.SUCCEEDED
    )


@pytest.mark.asyncio
async def test_process_timeout_marks_failed_and_removes_temp(
    monkeypatch, tmp_path
) -> None:
    draft = _draft()
    review = _review(draft)
    create_uow = FakeUow(draft, review)
    created = await ExportService(create_uow).create_initial(
        draft.id,
        draft.version,
        "PDF",
        "Editor",
        "export-key-0000005",
        "request-5",
    )
    tx_uow = FakeTxUow(draft, review)
    tx_uow.document_exports.items[created.export.id] = created.export
    tx_uow.export_attempts.items[created.attempt.id] = created.attempt
    monkeypatch.setattr(export_service_module, "UnitOfWork", lambda: tx_uow)
    storage = LocalArtifactStorage(tmp_path)
    service = ExportService(
        None,
        storage=storage,
        supervisor=FakeSupervisor(GenerationTimeoutError()),
        integrity=FakeIntegrity(),
    )

    await service.process(created.processing)

    assert not storage.exists(created.processing.relative_path)
    assert (
        tx_uow.document_exports.items[created.export.id].status == ExportStatus.FAILED
    )
    attempt = tx_uow.export_attempts.items[created.attempt.id]
    assert attempt.status == ExportAttemptStatus.FAILED
    assert attempt.error_code == "GENERATION_TIMEOUT"
