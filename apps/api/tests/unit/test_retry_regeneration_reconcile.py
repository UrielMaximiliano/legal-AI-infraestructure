"""Unit coverage for retry, regeneration and reconciliation phases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import pytest

from legal_ai.application.export_service import ExportService
from legal_ai.application.reconcile_service import (
    ReconcileFilters,
    ReconcileService,
)
from legal_ai.domain.document_export import DocumentExport
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import (
    DraftStatus,
    ExportAttemptStatus,
    ExportFormat,
    ExportStatus,
    ReviewStatus,
)
from legal_ai.domain.errors import (
    CleanupConflictError,
    ExportInProgressError,
    ExportVersionMismatchError,
    FilesystemError,
    IdempotencyConflictError,
    InvalidExportTransitionError,
    ValidationDomainError,
)
from legal_ai.domain.export_attempt import ExportAttempt
from legal_ai.domain.review import DocumentReview
from legal_ai.domain.review_event import ReviewEvent


def _draft() -> Draft:
    now = datetime.now(UTC)
    draft_id = uuid4()
    return Draft(
        id=draft_id,
        template_id=uuid4(),
        case_file_id=uuid4(),
        title="Synthetic",
        status=DraftStatus.APROBADO,
        version=3,
        generation_number=1,
        context_snapshot={},
        context_hash="a" * 64,
        created_at=now,
        updated_at=now,
        content="Approved",
        finalized_by="Editor",
        finalized_at=now,
        final_snapshot={"document": {"title": "Synthetic"}},
        final_snapshot_sha256="b" * 64,
    )


def _review(draft: Draft) -> DocumentReview:
    now = datetime.now(UTC)
    return DocumentReview(
        id=uuid4(),
        draft_id=draft.id,
        draft_version=draft.version,
        review_snapshot=draft.final_snapshot or {},
        review_snapshot_sha256="c" * 64,
        status=ReviewStatus.CLOSED,
        opened_by="Reviewer",
        version=1,
        opened_at=now,
        created_at=now,
        updated_at=now,
        closed_at=now,
    )


class _Drafts:
    def __init__(self, draft: Draft) -> None:
        self.draft = draft

    async def get_by_id(self, draft_id: UUID):
        return self.draft if draft_id == self.draft.id else None

    async def get_by_id_for_update(self, draft_id: UUID):
        return await self.get_by_id(draft_id)


class _Reviews:
    def __init__(self, review: DocumentReview) -> None:
        self.review = review

    async def get_latest_for_draft(self, draft_id: UUID):
        return self.review if draft_id == self.review.draft_id else None


class _Exports:
    def __init__(self) -> None:
        self.items: dict[UUID, DocumentExport] = {}

    async def get_by_id(self, export_id: UUID):
        return self.items.get(export_id)

    async def get_by_id_for_update(self, export_id: UUID):
        return await self.get_by_id(export_id)

    async def get_active(self, draft_id: UUID, export_format: ExportFormat):
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

    async def next_version(self, draft_id: UUID, export_format: ExportFormat):
        versions = [
            item.export_version
            for item in self.items.values()
            if item.draft_id == draft_id and item.format == export_format
        ]
        return max(versions, default=0) + 1

    async def create(self, export: DocumentExport):
        self.items[export.id] = export
        return export

    async def update_status(self, export_id: UUID, status: ExportStatus, **values):
        export = self.items[export_id]
        export.status = status
        for name, value in values.items():
            setattr(export, name, value)
        return export

    async def mark_previous_generated(
        self, draft_id: UUID, export_format: ExportFormat, exclude_id: UUID
    ) -> None:
        for export in self.items.values():
            if (
                export.draft_id == draft_id
                and export.format == export_format
                and export.id != exclude_id
                and export.status == ExportStatus.GENERATED
            ):
                export.status = ExportStatus.SUPERSEDED

    async def list_for_reconcile(self, draft_id=None, export_format=None):
        return [
            (export, uuid4())
            for export in self.items.values()
            if (draft_id is None or export.draft_id == draft_id)
            and (export_format is None or export.format == export_format)
        ]


class _Attempts:
    def __init__(self) -> None:
        self.items: dict[UUID, ExportAttempt] = {}

    async def get_by_id(self, attempt_id: UUID):
        return self.items.get(attempt_id)

    async def get_latest(self, export_id: UUID):
        values = [item for item in self.items.values() if item.export_id == export_id]
        return max(values, key=lambda item: item.attempt_number, default=None)

    async def get_latest_by_draft_key(
        self, draft_id: UUID, key: str, export_format=None
    ):
        values = [
            item
            for item in self.items.values()
            if item.draft_id == draft_id
            and item.idempotency_key == key
            and (export_format is None or item.format == export_format)
        ]
        return max(values, key=lambda item: item.created_at, default=None)

    async def next_attempt_number(self, export_id: UUID):
        latest = await self.get_latest(export_id)
        return (latest.attempt_number if latest else 0) + 1

    async def create(self, attempt: ExportAttempt):
        self.items[attempt.id] = attempt
        return attempt

    async def update(self, attempt: ExportAttempt):
        self.items[attempt.id] = attempt
        return attempt

    async def list_by_export(self, export_id, offset, limit):
        values = [item for item in self.items.values() if item.export_id == export_id]
        return values[offset : offset + limit], len(values)

    async def list_for_reconcile(self):
        return list(self.items.values())

    async def delete(self, attempt_id: UUID):
        del self.items[attempt_id]


class _Events:
    def __init__(self) -> None:
        self.items: list[ReviewEvent] = []

    async def get_reconciliation_run(self, run_id: UUID):
        return next(
            (
                item
                for item in self.items
                if item.event_type == "RECONCILIATION_RUN" and item.run_id == run_id
            ),
            None,
        )

    async def get_orphan_detection(self, fingerprint: str):
        return next(
            (
                item
                for item in self.items
                if item.event_type == "ORPHAN_DETECTED"
                and item.resource_id == fingerprint
            ),
            None,
        )

    async def create(self, event: ReviewEvent):
        self.items.append(event)
        return event


class _Uow:
    def __init__(self, draft: Draft, review: DocumentReview) -> None:
        self.drafts = _Drafts(draft)
        self.reviews = _Reviews(review)
        self.document_exports = _Exports()
        self.export_attempts = _Attempts()
        self.review_events = _Events()


class _Storage:
    def __init__(self, files: list[tuple[str, int, float]]) -> None:
        self.files = files
        self.deleted: list[str] = []

    def health(self) -> bool:
        return True

    def scan_files(self):
        return self.files

    def exists(self, relative_path: str) -> bool:
        return False

    def delete_scanned(self, relative_path: str) -> None:
        self.deleted.append(relative_path)


@pytest.mark.asyncio
async def test_retry_reuses_export_and_increments_attempt_number() -> None:
    draft = _draft()
    uow = _Uow(draft, _review(draft))
    service = ExportService(uow)
    initial = await service.create_initial(
        draft.id, draft.version, "DOCX", "Editor", "retry-key-000001", "r1"
    )
    initial.export.status = ExportStatus.FAILED
    initial.attempt.status = ExportAttemptStatus.FAILED
    retried = await service.retry_failed(
        initial.export.id, "Editor", "retry-key-000001", "r2"
    )
    assert retried.status_code == 202
    assert retried.export.id == initial.export.id
    assert retried.attempt.attempt_number == 2
    assert retried.attempt.status == ExportAttemptStatus.PROCESSING
    assert len(uow.document_exports.items) == 1


@pytest.mark.asyncio
async def test_retry_active_and_payload_conflict_are_rejected() -> None:
    draft = _draft()
    uow = _Uow(draft, _review(draft))
    service = ExportService(uow)
    initial = await service.create_initial(
        draft.id, draft.version, "PDF", "Editor", "retry-key-000002", "r1"
    )
    initial.export.status = ExportStatus.FAILED
    initial.attempt.status = ExportAttemptStatus.FAILED
    retry = await service.retry_failed(
        initial.export.id, "Editor", "retry-key-000002", "r2"
    )
    with pytest.raises(ExportInProgressError):
        await service.retry_failed(
            initial.export.id, "Editor", "retry-key-000002", "r3"
        )
    retry.export.status = ExportStatus.FAILED
    retry.attempt.status = ExportAttemptStatus.FAILED
    with pytest.raises(IdempotencyConflictError):
        await service.retry_failed(
            initial.export.id, "Other", "retry-key-000002", "r4"
        )


@pytest.mark.asyncio
async def test_retry_success_is_idempotent_replay() -> None:
    draft = _draft()
    uow = _Uow(draft, _review(draft))
    service = ExportService(uow)
    initial = await service.create_initial(
        draft.id, draft.version, "DOCX", "Editor", "retry-key-000003", "r1"
    )
    initial.export.status = ExportStatus.FAILED
    initial.attempt.status = ExportAttemptStatus.FAILED
    retry = await service.retry_failed(
        initial.export.id, "Editor", "retry-key-000003", "r2"
    )
    retry.export.status = ExportStatus.GENERATED
    retry.attempt.status = ExportAttemptStatus.SUCCEEDED
    replay = await service.retry_failed(
        initial.export.id, "Editor", "retry-key-000003", "r3"
    )
    assert replay.status_code == 200
    assert replay.export.id == initial.export.id
    assert replay.attempt.id == retry.attempt.id


@pytest.mark.asyncio
async def test_regeneration_uses_snapshot_and_parent_without_source_file() -> None:
    draft = _draft()
    uow = _Uow(draft, _review(draft))
    source = DocumentExport(
        id=uuid4(),
        draft_id=draft.id,
        draft_version=draft.version,
        review_id=uow.reviews.review.id,
        export_version=1,
        format=ExportFormat.PDF,
        status=ExportStatus.GENERATED,
        file_name=f"{draft.id}_v1.pdf",
        source_snapshot_sha256=draft.final_snapshot_sha256 or "b" * 64,
        exported_by="Editor",
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )
    await uow.document_exports.create(source)
    service = ExportService(uow)
    result = await service.regenerate(
        source.id, 1, "Editor", "regen-key-000001", "r1"
    )
    assert result.status_code == 202
    assert result.export.parent_export_id == source.id
    assert result.export.export_version == 2
    assert result.export.file_name.endswith("_v2.pdf")
    assert result.processing is not None
    assert result.processing.snapshot == draft.final_snapshot
    result.export.status = ExportStatus.FAILED
    result.attempt.status = ExportAttemptStatus.FAILED

    with pytest.raises(ExportVersionMismatchError):
        await service.regenerate(
            source.id, 1, "Editor", "regen-key-000002", "r2"
        )


@pytest.mark.asyncio
async def test_regeneration_replay_conflict_and_invalid_source() -> None:
    draft = _draft()
    uow = _Uow(draft, _review(draft))
    source = DocumentExport(
        id=uuid4(),
        draft_id=draft.id,
        draft_version=draft.version,
        review_id=uow.reviews.review.id,
        export_version=1,
        format=ExportFormat.DOCX,
        status=ExportStatus.FAILED,
        file_name=f"{draft.id}_v1.docx",
        source_snapshot_sha256="b" * 64,
        exported_by="Editor",
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )
    await uow.document_exports.create(source)
    service = ExportService(uow)
    with pytest.raises(InvalidExportTransitionError):
        await service.regenerate(source.id, 1, "Editor", "regen-key-000003", "r1")

    source.status = ExportStatus.GENERATED
    result = await service.regenerate(
        source.id, 1, "Editor", "regen-key-000003", "r2"
    )
    result.export.status = ExportStatus.GENERATED
    result.attempt.status = ExportAttemptStatus.SUCCEEDED
    replay = await service.regenerate(
        source.id, 1, "Editor", "regen-key-000003", "r3"
    )
    assert replay.status_code == 200
    with pytest.raises(IdempotencyConflictError):
        await service.regenerate(
            source.id, 1, "Other", "regen-key-000003", "r4"
        )


@pytest.mark.asyncio
async def test_reconcile_dry_run_execute_and_run_replay() -> None:
    draft = _draft()
    uow = _Uow(draft, _review(draft))
    old = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    storage = _Storage([("tmp-old.docx", 10, old)])
    service = ReconcileService(uow, storage=storage, now=datetime.now(UTC))
    run_id = uuid4()

    dry = await service.reconcile(actor="Admin", run_id=run_id)
    assert dry["mode"] == "dry-run"
    assert dry["deleted"] == 0
    assert storage.deleted == []

    replay = await service.reconcile(actor="Admin", run_id=run_id)
    assert replay == dry

    with pytest.raises(CleanupConflictError):
        await service.reconcile(actor="Different", run_id=run_id)

    executed = await ReconcileService(
        uow, storage=storage, now=datetime.now(UTC)
    ).reconcile(actor="Admin", execute=True)
    assert executed["deleted"] == 1
    assert storage.deleted == ["tmp-old.docx"]


@pytest.mark.asyncio
async def test_reconcile_filters_validation_and_missing_file() -> None:
    draft = _draft()
    uow = _Uow(draft, _review(draft))
    missing = DocumentExport(
        id=uuid4(),
        draft_id=draft.id,
        draft_version=draft.version,
        review_id=uow.reviews.review.id,
        export_version=1,
        format=ExportFormat.PDF,
        status=ExportStatus.GENERATED,
        file_name=f"{draft.id}_v1.pdf",
        source_snapshot_sha256="b" * 64,
        content_sha256="c" * 64,
        storage_path="missing.pdf",
        exported_by="Editor",
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )
    await uow.document_exports.create(missing)
    service = ReconcileService(uow, storage=_Storage([]))
    result = await service.reconcile(actor="Admin", incident_type="MISSING_FILE")
    assert result["omitted"] == 1
    with pytest.raises(ValidationDomainError):
        await service.reconcile(actor="Admin", format="HTML")
    with pytest.raises(ValidationDomainError):
        await service.reconcile(actor="Admin", older_than="not-a-duration")


@pytest.mark.asyncio
async def test_reconcile_helpers_cover_fallback_and_incomplete_states() -> None:
    draft = _draft()
    uow = _Uow(draft, _review(draft))
    service = ReconcileService(uow, storage=_Storage([]))
    filters = ReconcileFilters()
    exports_repository = uow.document_exports
    attempts_repository = uow.export_attempts
    uow.document_exports = object()
    uow.export_attempts = object()
    assert len(await service._list_exports(filters)) == 0
    assert len(await service._list_attempts()) == 0
    uow.document_exports = exports_repository
    uow.export_attempts = attempts_repository
    assert len(ReconcileService.filters_hash(filters, "Admin", False)) == 64
    assert ReconcileService._matches_file(PurePosixPath("case/draft/file"), filters)
    assert not ReconcileService._file_has_processing_export(
        PurePosixPath("case/draft/file"), set()
    )

    pending = DocumentExport(
        id=uuid4(),
        draft_id=draft.id,
        draft_version=draft.version,
        review_id=uow.reviews.review.id,
        export_version=1,
        format=ExportFormat.PDF,
        status=ExportStatus.GENERATING,
        file_name=f"{draft.id}_v1.pdf",
        source_snapshot_sha256="b" * 64,
        exported_by="Editor",
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )
    await uow.document_exports.create(pending)
    result = await service.reconcile(actor="Admin", incident_type="INCOMPLETE_DB")
    assert result["omitted"] == 1

    service._storage = type("Unavailable", (), {"health": lambda self: False})()
    with pytest.raises(FilesystemError):
        service._scan_files()


@pytest.mark.asyncio
async def test_reconcile_run_alias_and_filter_mismatch() -> None:
    draft = _draft()
    uow = _Uow(draft, _review(draft))
    service = ReconcileService(uow, storage=_Storage([]))
    result = await service.run(actor="Admin")
    assert result["mode"] == "dry-run"
    no_match = await service.reconcile(actor="Admin", draft_id=uuid4())
    assert no_match["candidates"] == 0
