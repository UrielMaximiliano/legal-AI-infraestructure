"""Application services for initial export and read/download operations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.renderers.canonical_html_renderer import (
    SafeCanonicalHtmlRenderer,
)
from legal_ai.adapters.renderers.docx_renderer import PythonDocxRenderer
from legal_ai.adapters.renderers.pdf_renderer import WeasyPrintPdfRenderer
from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage
from legal_ai.application.artifact_integrity import (
    DOCX_MIME,
    PDF_MIME,
    ArtifactIntegrityValidator,
)
from legal_ai.application.renderer_supervisor import RendererSupervisor
from legal_ai.domain.document_export import DocumentExport
from legal_ai.domain.enums import (
    DraftStatus,
    ExportAttemptStatus,
    ExportFormat,
    ExportStatus,
    ReviewStatus,
)
from legal_ai.domain.errors import (
    ActiveGenerationExistsError,
    DomainError,
    DraftNotApprovedError,
    DraftNotFinalizedError,
    ExportFileCorruptedError,
    ExportFileNotFoundError,
    ExportFormatUnsupportedError,
    ExportInProgressError,
    ExportNotFoundError,
    ExportVersionMismatchError,
    HashValidationError,
    IdempotencyConflictError,
    InvalidArtifactError,
    InvalidExportTransitionError,
    PathValidationError,
    ValidationDomainError,
)
from legal_ai.domain.export_attempt import ExportAttempt
from legal_ai.domain.review_event import ReviewEvent
from legal_ai.observability.logging import log_event
from legal_ai.schemas.validation import validate_actor, validate_idempotency_key


@dataclass(frozen=True)
class ExportProcessingContext:
    """Serializable data captured in Tx1 and consumed after its commit."""

    export_id: UUID
    attempt_id: UUID
    draft_id: UUID
    case_file_id: UUID
    draft_version: int
    export_version: int
    format: ExportFormat
    file_name: str
    relative_path: str
    source_snapshot_sha256: str
    snapshot: dict[str, Any]
    request_id: str
    exported_by: str


@dataclass(frozen=True)
class ExportOperationResult:
    export: DocumentExport
    attempt: ExportAttempt
    status_code: int
    processing: ExportProcessingContext | None = None


@dataclass(frozen=True)
class DownloadResult:
    export: DocumentExport
    relative_path: str
    content_type: str
    content_length: int
    etag: str


class ExportService:
    """Coordinate short DB transactions and filesystem/rendering boundaries."""

    def __init__(
        self,
        uow: UnitOfWork | None,
        *,
        storage: LocalArtifactStorage | None = None,
        integrity: ArtifactIntegrityValidator | None = None,
        supervisor: RendererSupervisor | None = None,
        html_renderer: SafeCanonicalHtmlRenderer | None = None,
        docx_renderer: PythonDocxRenderer | None = None,
        pdf_renderer: WeasyPrintPdfRenderer | None = None,
    ) -> None:
        self._uow = uow
        self._storage = storage or LocalArtifactStorage()
        self._integrity = integrity or ArtifactIntegrityValidator()
        self._supervisor = supervisor or RendererSupervisor()
        self._html_renderer = html_renderer or SafeCanonicalHtmlRenderer()
        self._docx_renderer = docx_renderer or PythonDocxRenderer()
        self._pdf_renderer = pdf_renderer or WeasyPrintPdfRenderer()

    async def create_initial(
        self,
        draft_id: UUID,
        draft_version: int,
        raw_format: str,
        exported_by: str,
        idempotency_key: str,
        request_id: str,
    ) -> ExportOperationResult:
        """Claim an initial export in exactly one short Tx1."""
        if self._uow is None:
            raise RuntimeError("create_initial requires a UnitOfWork")
        export_format = self._format(raw_format)
        actor = self._actor(exported_by)
        key = self._key(idempotency_key)
        request_hash = self.request_hash(draft_version, export_format, actor)
        now = datetime.now(UTC)

        draft = await self._uow.drafts.get_by_id_for_update(draft_id)
        if draft is None:
            from legal_ai.domain.errors import DraftNotFound004Error

            raise DraftNotFound004Error()
        if draft.status != DraftStatus.APROBADO:
            raise DraftNotApprovedError()
        if not draft.is_finalized():
            raise DraftNotFinalizedError()
        if draft.version != draft_version:
            from legal_ai.domain.errors import ConcurrentModification004Error

            raise ConcurrentModification004Error()
        if (
            not isinstance(draft.final_snapshot, dict)
            or not draft.final_snapshot_sha256
        ):
            raise DraftNotFinalizedError()

        existing = await self._uow.export_attempts.get_latest_by_draft_key(
            draft_id, key
        )
        if existing is not None and self._within_idempotency_window(
            existing.created_at, now
        ):
            if existing.request_hash != request_hash:
                from legal_ai.domain.errors import IdempotencyConflictError

                raise IdempotencyConflictError()
            existing_export = await self._uow.document_exports.get_by_id(
                existing.export_id
            )
            if existing_export is not None:
                if existing.status in {
                    ExportAttemptStatus.PENDING,
                    ExportAttemptStatus.PROCESSING,
                }:
                    raise ExportInProgressError()
                if existing.status in {
                    ExportAttemptStatus.SUCCEEDED,
                    ExportAttemptStatus.FAILED,
                }:
                    return ExportOperationResult(
                        existing_export, existing, 200, processing=None
                    )

        active = await self._uow.document_exports.get_active(draft_id, export_format)
        if active is not None:
            raise ActiveGenerationExistsError()

        review = await self._uow.reviews.get_latest_for_draft(draft_id)
        if review is None or review.status != ReviewStatus.CLOSED:
            raise DraftNotFinalizedError()

        export_version = await self._uow.document_exports.next_version(
            draft_id, export_format
        )
        file_name = f"{draft.id}_v{export_version}.{export_format.value.lower()}"
        relative_path = self._storage.build_relative_path(
            draft.case_file_id,
            draft.id,
            export_format.value,
            export_version,
            file_name,
        )
        export = DocumentExport(
            id=uuid4(),
            draft_id=draft.id,
            draft_version=draft.version,
            review_id=review.id,
            export_version=export_version,
            format=export_format,
            status=ExportStatus.PENDING,
            file_name=file_name,
            source_snapshot_sha256=draft.final_snapshot_sha256,
            exported_by=actor,
            created_at=now,
            updated_at=now,
        )
        attempt = ExportAttempt(
            id=uuid4(),
            export_id=export.id,
            draft_id=draft.id,
            format=export_format,
            idempotency_key=key,
            request_hash=request_hash,
            attempt_number=1,
            status=ExportAttemptStatus.PENDING,
            request_id=request_id,
            exported_by=actor,
            created_at=now,
            started_at=None,
            updated_at=now,
        )
        try:
            await self._uow.document_exports.create(export)
            export = (
                await self._uow.document_exports.update_status(
                    export.id, ExportStatus.GENERATING, updated_at=now
                )
                or export
            )
            await self._uow.export_attempts.create(attempt)
            attempt.status = ExportAttemptStatus.PROCESSING
            attempt.started_at = now
            attempt.updated_at = now
            attempt = await self._uow.export_attempts.update(attempt)
        except IntegrityError as exc:
            raise ActiveGenerationExistsError() from exc

        processing = ExportProcessingContext(
            export_id=export.id,
            attempt_id=attempt.id,
            draft_id=draft.id,
            case_file_id=draft.case_file_id,
            draft_version=draft.version,
            export_version=export_version,
            format=export_format,
            file_name=file_name,
            relative_path=relative_path,
            source_snapshot_sha256=draft.final_snapshot_sha256,
            snapshot=draft.final_snapshot,
            request_id=request_id,
            exported_by=actor,
        )
        log_event(
            "export_tx1_committed",
            request_id=request_id,
            draft_id=draft.id,
            case_file_id=draft.case_file_id,
            export_id=export.id,
            attempt_id=attempt.id,
            format=export.format.value,
            export_version=export.export_version,
            attempt_number=attempt.attempt_number,
            phase="tx1",
            status=export.status.value,
            result="accepted",
        )
        return ExportOperationResult(export, attempt, 202, processing)

    async def process(self, context: ExportProcessingContext) -> None:
        """Render and publish outside PostgreSQL, then execute Tx2."""
        temporary: Path | None = None
        published = False
        artifact_size: int | None = None
        total_started = time.perf_counter()
        common: dict[str, Any] = {
            "request_id": context.request_id,
            "draft_id": context.draft_id,
            "case_file_id": context.case_file_id,
            "export_id": context.export_id,
            "attempt_id": context.attempt_id,
            "format": context.format.value,
            "export_version": context.export_version,
        }
        try:
            temporary = self._storage.create_temp(context.relative_path)
            if context.format == ExportFormat.PDF:
                input_data: Any = self._html_renderer.render(context.snapshot)
                renderer: Any = self._pdf_renderer
                timeout = getattr(renderer, "timeout_seconds", 60)
                mime = PDF_MIME
            else:
                input_data = context.snapshot
                renderer = self._docx_renderer
                timeout = getattr(renderer, "timeout_seconds", 30)
                mime = DOCX_MIME
            render_started = time.perf_counter()
            log_event(
                "export_render_started",
                **common,
                renderer=getattr(renderer, "name", renderer.__class__.__name__),
                phase="render",
                status="PROCESSING",
            )
            await asyncio.to_thread(
                self._supervisor.run,
                renderer,
                input_data,
                temporary,
                timeout,
            )
            log_event(
                "export_render_completed",
                **common,
                renderer=getattr(renderer, "name", renderer.__class__.__name__),
                phase="render",
                duration_ms=round((time.perf_counter() - render_started) * 1000, 3),
                result="success",
            )
            validation_started = time.perf_counter()
            if context.format == ExportFormat.PDF:
                digest = self._integrity.validate_pdf(temporary, declared_mime=mime)
            else:
                digest = self._integrity.validate_docx(temporary, declared_mime=mime)
            validation_duration = round(
                (time.perf_counter() - validation_started) * 1000, 3
            )
            artifact_size = temporary.stat().st_size
            log_event(
                "export_validation_completed",
                **common,
                phase="validate",
                validation_duration_ms=validation_duration,
                size_bytes=artifact_size,
                sha256=digest,
                result="success",
            )
            self._storage.atomic_replace(temporary, context.relative_path)
            published = True
            log_event(
                "export_rename_completed",
                **common,
                phase="rename",
                result="success",
            )
            await self._complete_success(context, digest, renderer)
            log_event(
                "export_completed",
                **common,
                total_duration_ms=round(
                    (time.perf_counter() - total_started) * 1000, 3
                ),
                size_bytes=artifact_size,
                sha256=digest,
                result="success",
            )
        except DomainError as exc:
            await self._cleanup_artifact(temporary, context.relative_path, published)
            log_event(
                "export_processing_failed",
                **common,
                phase="compensation",
                duration_ms=round((time.perf_counter() - total_started) * 1000, 3),
                total_duration_ms=round(
                    (time.perf_counter() - total_started) * 1000, 3
                ),
                error_code=exc.code,
                result="failed",
            )
            await self._complete_failure(context, exc.code, self._safe_message(exc))
        except Exception:
            await self._cleanup_artifact(temporary, context.relative_path, published)
            log_event(
                "export_processing_failed",
                **common,
                phase="compensation",
                duration_ms=round((time.perf_counter() - total_started) * 1000, 3),
                total_duration_ms=round(
                    (time.perf_counter() - total_started) * 1000, 3
                ),
                error_code="EXPORT_GENERATION_FAILED",
                result="failed",
            )
            await self._complete_failure(
                context, "EXPORT_GENERATION_FAILED", "La generación del artefacto falló"
            )

    async def retry_failed(
        self,
        export_id: UUID,
        exported_by: str,
        idempotency_key: str,
        request_id: str,
    ) -> ExportOperationResult:
        """Claim another attempt for one FAILED export in Tx1."""
        if self._uow is None:
            raise RuntimeError("retry_failed requires a UnitOfWork")
        actor = self._actor(exported_by)
        key = self._key(idempotency_key)
        existing_export = await self._uow.document_exports.get_by_id(export_id)
        if existing_export is None:
            raise ExportNotFoundError()
        draft = await self._uow.drafts.get_by_id_for_update(existing_export.draft_id)
        if draft is None:
            from legal_ai.domain.errors import DraftNotFound004Error

            raise DraftNotFound004Error()
        export = await self._uow.document_exports.get_by_id_for_update(export_id)
        if export is None:
            raise ExportNotFoundError()
        latest = await self._uow.export_attempts.get_latest(export.id)
        if latest is None:
            raise InvalidExportTransitionError()
        expected_hash = self.request_hash(export.draft_version, export.format, actor)
        if (
            latest.idempotency_key != key
            or latest.request_hash != expected_hash
            or actor != export.exported_by
        ):
            raise IdempotencyConflictError()
        if latest.status in {
            ExportAttemptStatus.PENDING,
            ExportAttemptStatus.PROCESSING,
        }:
            raise ExportInProgressError()
        if latest.status == ExportAttemptStatus.SUCCEEDED:
            return ExportOperationResult(export, latest, 200)
        if export.status != ExportStatus.FAILED:
            raise InvalidExportTransitionError()
        active = await self._uow.document_exports.get_active(
            export.draft_id, export.format
        )
        if active is not None and active.id != export.id:
            raise ActiveGenerationExistsError()
        if (
            not isinstance(draft.final_snapshot, dict)
            or not draft.final_snapshot_sha256
        ):
            raise DraftNotFinalizedError()

        now = datetime.now(UTC)
        attempt = ExportAttempt(
            id=uuid4(),
            export_id=export.id,
            draft_id=export.draft_id,
            format=export.format,
            idempotency_key=key,
            request_hash=latest.request_hash,
            attempt_number=await self._uow.export_attempts.next_attempt_number(
                export.id
            ),
            status=ExportAttemptStatus.PROCESSING,
            request_id=request_id,
            exported_by=actor,
            created_at=now,
            started_at=now,
            updated_at=now,
        )
        try:
            updated = await self._uow.document_exports.update_status(
                export.id,
                ExportStatus.GENERATING,
                updated_at=now,
                completed_at=None,
                error_code=None,
                error_message=None,
            )
            await self._uow.export_attempts.create(attempt)
        except IntegrityError as exc:
            raise ExportInProgressError() from exc
        if updated is not None:
            export = updated
        else:
            export.status = ExportStatus.GENERATING
            export.updated_at = now
            export.completed_at = None
            export.error_code = None
            export.error_message = None
        context = self._processing_context(export, attempt, draft, request_id)
        log_event(
            "export_retry_tx1_committed",
            request_id=request_id,
            draft_id=export.draft_id,
            export_id=export.id,
            attempt_id=attempt.id,
            format=export.format.value,
            export_version=export.export_version,
            attempt_number=attempt.attempt_number,
            phase="tx1",
            status=export.status.value,
            result="accepted",
        )
        return ExportOperationResult(export, attempt, 202, context)

    async def regenerate(
        self,
        export_id: UUID,
        expected_version: int,
        exported_by: str,
        idempotency_key: str,
        request_id: str,
    ) -> ExportOperationResult:
        """Create a new export version from final_snapshot in Tx1."""
        if self._uow is None:
            raise RuntimeError("regenerate requires a UnitOfWork")
        actor = self._actor(exported_by)
        key = self._key(idempotency_key)
        source = await self._uow.document_exports.get_by_id(export_id)
        if source is None:
            raise ExportNotFoundError()
        request_hash = self.regeneration_request_hash(
            source.id, expected_version, source.format, actor
        )
        existing_attempt = await self._latest_by_draft_key(
            source.draft_id, key, source.format
        )
        if existing_attempt is not None:
            if existing_attempt.request_hash != request_hash:
                raise IdempotencyConflictError()
            existing_result = await self._uow.document_exports.get_by_id(
                existing_attempt.export_id
            )
            if existing_result is not None:
                if existing_attempt.status == ExportAttemptStatus.PROCESSING:
                    raise ExportInProgressError()
                if existing_attempt.status in {
                    ExportAttemptStatus.SUCCEEDED,
                    ExportAttemptStatus.FAILED,
                }:
                    return ExportOperationResult(existing_result, existing_attempt, 200)

        draft = await self._uow.drafts.get_by_id_for_update(source.draft_id)
        if draft is None:
            from legal_ai.domain.errors import DraftNotFound004Error

            raise DraftNotFound004Error()
        source = await self._uow.document_exports.get_by_id_for_update(source.id)
        if source is None:
            raise ExportNotFoundError()
        if source.status not in {ExportStatus.GENERATED, ExportStatus.SUPERSEDED}:
            raise InvalidExportTransitionError()
        active = await self._uow.document_exports.get_active(
            source.draft_id, source.format
        )
        if active is not None:
            raise ExportInProgressError()
        next_version = await self._uow.document_exports.next_version(
            source.draft_id, source.format
        )
        if expected_version != next_version - 1:
            raise ExportVersionMismatchError()
        if (
            not isinstance(draft.final_snapshot, dict)
            or not draft.final_snapshot_sha256
        ):
            raise DraftNotFinalizedError()

        now = datetime.now(UTC)
        file_name = f"{draft.id}_v{next_version}.{source.format.value.lower()}"
        export = DocumentExport(
            id=uuid4(),
            draft_id=draft.id,
            draft_version=draft.version,
            review_id=source.review_id,
            export_version=next_version,
            format=source.format,
            status=ExportStatus.GENERATING,
            file_name=file_name,
            source_snapshot_sha256=draft.final_snapshot_sha256,
            exported_by=actor,
            parent_export_id=source.id,
            created_at=now,
            updated_at=now,
        )
        attempt = ExportAttempt(
            id=uuid4(),
            export_id=export.id,
            draft_id=draft.id,
            format=source.format,
            idempotency_key=key,
            request_hash=request_hash,
            attempt_number=1,
            status=ExportAttemptStatus.PROCESSING,
            request_id=request_id,
            exported_by=actor,
            created_at=now,
            started_at=now,
            updated_at=now,
        )
        try:
            await self._uow.document_exports.create(export)
            await self._uow.export_attempts.create(attempt)
        except IntegrityError as exc:
            raise ActiveGenerationExistsError() from exc
        context = self._processing_context(export, attempt, draft, request_id)
        log_event(
            "export_regeneration_tx1_committed",
            request_id=request_id,
            draft_id=export.draft_id,
            export_id=export.id,
            attempt_id=attempt.id,
            format=export.format.value,
            export_version=export.export_version,
            attempt_number=attempt.attempt_number,
            phase="tx1",
            status=export.status.value,
            result="accepted",
        )
        return ExportOperationResult(export, attempt, 202, context)

    async def _latest_by_draft_key(
        self, draft_id: UUID, key: str, export_format: ExportFormat
    ) -> ExportAttempt | None:
        if self._uow is None:
            raise RuntimeError("idempotency lookup requires a UnitOfWork")
        try:
            return await self._uow.export_attempts.get_latest_by_draft_key(
                draft_id, key, export_format
            )
        except TypeError:
            return await self._uow.export_attempts.get_latest_by_draft_key(
                draft_id, key
            )

    def _processing_context(
        self,
        export: DocumentExport,
        attempt: ExportAttempt,
        draft: Any,
        request_id: str,
    ) -> ExportProcessingContext:
        if not isinstance(draft.final_snapshot, dict):
            raise DraftNotFinalizedError()
        return ExportProcessingContext(
            export_id=export.id,
            attempt_id=attempt.id,
            draft_id=export.draft_id,
            case_file_id=draft.case_file_id,
            draft_version=export.draft_version,
            export_version=export.export_version,
            format=export.format,
            file_name=export.file_name,
            relative_path=self._storage.build_relative_path(
                draft.case_file_id,
                draft.id,
                export.format.value,
                export.export_version,
                export.file_name,
            ),
            source_snapshot_sha256=export.source_snapshot_sha256,
            snapshot=draft.final_snapshot,
            request_id=request_id,
            exported_by=export.exported_by,
        )

    async def list_exports(
        self,
        draft_id: UUID,
        *,
        page: int,
        page_size: int,
        raw_format: str | None = None,
        status: str | None = None,
        draft_version: int | None = None,
        export_version: int | None = None,
    ) -> tuple[list[DocumentExport], int]:
        if self._uow is None:
            raise RuntimeError("list_exports requires a UnitOfWork")
        if page_size > 100 or page < 1:
            raise ValidationDomainError(details={"field": "page_size"})
        export_format = self._format(raw_format) if raw_format else None
        export_status = self._status(status) if status else None
        if await self._uow.drafts.get_by_id(draft_id) is None:
            from legal_ai.domain.errors import DraftNotFound004Error

            raise DraftNotFound004Error()
        return await self._uow.document_exports.list_by_draft(
            draft_id,
            (page - 1) * page_size,
            page_size,
            export_format,
            draft_version,
            export_version,
            export_status,
        )

    async def get_export(self, export_id: UUID) -> DocumentExport:
        if self._uow is None:
            raise RuntimeError("get_export requires a UnitOfWork")
        export = await self._uow.document_exports.get_by_id(export_id)
        if export is None:
            raise ExportNotFoundError()
        return export

    async def list_attempts(
        self, export_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[ExportAttempt], int]:
        if self._uow is None:
            raise RuntimeError("list_attempts requires a UnitOfWork")
        if page < 1 or page_size > 100:
            raise ValidationDomainError(details={"field": "page_size"})
        if await self._uow.document_exports.get_by_id(export_id) is None:
            raise ExportNotFoundError()
        return await self._uow.export_attempts.list_by_export(
            export_id, (page - 1) * page_size, page_size
        )

    async def prepare_download(
        self, export_id: UUID, request_id: str = ""
    ) -> DownloadResult:
        export = await self.get_export(export_id)
        if not export.is_downloadable() or not export.storage_path:
            raise InvalidExportTransitionError()
        try:
            path = self._storage.resolve_relative(export.storage_path)
        except PathValidationError as exc:
            await self._record_integrity_failure(export, request_id)
            raise ExportFileCorruptedError() from exc
        if not path.is_file() or path.is_symlink():
            raise ExportFileNotFoundError()
        try:
            if export.format == ExportFormat.PDF:
                digest = self._integrity.validate_pdf(
                    path, expected_sha256=export.content_sha256, declared_mime=PDF_MIME
                )
                content_type = PDF_MIME
            else:
                digest = self._integrity.validate_docx(
                    path,
                    expected_sha256=export.content_sha256,
                    declared_mime=DOCX_MIME,
                )
                content_type = DOCX_MIME
        except (InvalidArtifactError, HashValidationError, PathValidationError) as exc:
            await self._record_integrity_failure(export, request_id)
            raise ExportFileCorruptedError() from exc
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ExportFileNotFoundError() from exc
        log_event(
            "download_integrity_verified",
            request_id=request_id,
            draft_id=export.draft_id,
            export_id=export.id,
            format=export.format.value,
            export_version=export.export_version,
            size_bytes=size,
            sha256=digest,
            phase="download_integrity",
            result="success",
        )
        return DownloadResult(
            export=export,
            relative_path=export.storage_path,
            content_type=content_type,
            content_length=size,
            etag=f'"sha256:{digest}"',
        )

    async def _complete_success(
        self,
        context: ExportProcessingContext,
        digest: str,
        renderer: Any,
    ) -> None:
        async with UnitOfWork() as uow:
            export = await uow.document_exports.get_by_id_for_update(context.export_id)
            attempt = await uow.export_attempts.get_by_id(context.attempt_id)
            if export is None or attempt is None:
                return
            now = datetime.now(UTC)
            await uow.document_exports.mark_previous_generated(
                context.draft_id, context.format, context.export_id
            )
            await uow.document_exports.update_status(
                context.export_id,
                ExportStatus.GENERATED,
                storage_path=context.relative_path,
                content_sha256=digest,
                renderer_name=getattr(renderer, "name", renderer.__class__.__name__),
                renderer_version=str(getattr(renderer, "version", "unknown")),
                completed_at=now,
                updated_at=now,
                error_code=None,
                error_message=None,
            )
            attempt.status = ExportAttemptStatus.SUCCEEDED
            attempt.completed_at = now
            attempt.updated_at = now
            await uow.export_attempts.update(attempt)
            log_event(
                "export_tx2_committed",
                request_id=context.request_id,
                draft_id=context.draft_id,
                case_file_id=context.case_file_id,
                export_id=context.export_id,
                attempt_id=context.attempt_id,
                format=context.format.value,
                export_version=context.export_version,
                phase="tx2",
                status=ExportStatus.GENERATED.value,
                result="success",
                sha256=digest,
            )

    async def _complete_failure(
        self, context: ExportProcessingContext, code: str, message: str
    ) -> None:
        async with UnitOfWork() as uow:
            export = await uow.document_exports.get_by_id_for_update(context.export_id)
            attempt = await uow.export_attempts.get_by_id(context.attempt_id)
            if export is None or attempt is None:
                return
            now = datetime.now(UTC)
            await uow.document_exports.update_status(
                context.export_id,
                ExportStatus.FAILED,
                updated_at=now,
                completed_at=now,
                error_code=code,
                error_message=message,
            )
            attempt.status = ExportAttemptStatus.FAILED
            attempt.completed_at = now
            attempt.updated_at = now
            attempt.error_code = code
            attempt.error_message = message
            await uow.export_attempts.update(attempt)
            log_event(
                "export_tx2_committed",
                request_id=context.request_id,
                draft_id=context.draft_id,
                case_file_id=context.case_file_id,
                export_id=context.export_id,
                attempt_id=context.attempt_id,
                format=context.format.value,
                export_version=context.export_version,
                phase="tx2",
                status=ExportStatus.FAILED.value,
                result="failed",
                error_code=code,
            )

    async def _cleanup_artifact(
        self, temporary: Path | None, relative_path: str, published: bool
    ) -> None:
        try:
            if published:
                self._storage.delete(relative_path)
            elif temporary is not None and temporary.exists():
                temporary.unlink()
        except OSError:
            log_event(
                "export_compensation_failed",
                phase="compensation",
                result="failed",
                error_code="FILESYSTEM_ERROR",
            )

    async def _record_integrity_failure(
        self, export: DocumentExport, request_id: str
    ) -> None:
        try:
            async with UnitOfWork() as uow:
                await uow.review_events.create(
                    ReviewEvent(
                        id=uuid4(),
                        resource_type="EXPORT",
                        event_type="DOWNLOAD_INTEGRITY_BLOCKED",
                        created_at=datetime.now(UTC),
                        review_id=export.review_id,
                        draft_id=export.draft_id,
                        export_id=export.id,
                        resource_id=str(export.id),
                        request_id=request_id,
                        draft_version=export.draft_version,
                        summary={"code": "EXPORT_FILE_CORRUPTED"},
                    )
                )
        except Exception:
            # Integrity failures must never expose database details or change
            # the public corruption response when audit persistence is down.
            log_event(
                "download_integrity_audit_failed",
                export_id=export.id,
                draft_id=export.draft_id,
                request_id=request_id,
                phase="download_integrity",
                error_code="DATABASE_ERROR",
                result="failed",
            )
            return

    @staticmethod
    def request_hash(
        draft_version: int, export_format: ExportFormat, actor: str
    ) -> str:
        payload = {
            "draft_version": draft_version,
            "format": export_format.value,
            "exported_by": actor,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def regeneration_request_hash(
        source_export_id: UUID,
        expected_version: int,
        export_format: ExportFormat,
        actor: str,
    ) -> str:
        """Hash the functional regeneration payload, excluding request_id."""
        payload = {
            "source_export_id": str(source_export_id),
            "expected_version": expected_version,
            "format": export_format.value,
            "exported_by": actor,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _format(raw_format: str | ExportFormat) -> ExportFormat:
        try:
            return ExportFormat(str(raw_format).upper())
        except ValueError as exc:
            raise ExportFormatUnsupportedError() from exc

    @staticmethod
    def _status(raw_status: str) -> ExportStatus:
        try:
            return ExportStatus(raw_status.upper())
        except ValueError as exc:
            raise ValidationDomainError(details={"field": "status"}) from exc

    @staticmethod
    def _actor(value: str) -> str:
        try:
            actor = validate_actor(value)
            if actor is None:
                raise ValueError
            return actor
        except ValueError as exc:
            raise ValidationDomainError(details={"field": "exported_by"}) from exc

    @staticmethod
    def _key(value: str) -> str:
        try:
            return validate_idempotency_key(value)
        except ValueError as exc:
            from legal_ai.domain.errors import IdempotencyKeyRequiredError

            raise IdempotencyKeyRequiredError() from exc

    @staticmethod
    def _within_idempotency_window(created_at: datetime, now: datetime) -> bool:
        from legal_ai.config import settings

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return (now - created_at).total_seconds() <= (
            settings.export.export_idempotency_window_hours * 3600
        )

    @staticmethod
    def _safe_message(exc: DomainError) -> str:
        return str(exc.message)[:300]

    @classmethod
    async def process_operation(cls, context: ExportProcessingContext) -> None:
        """Entry point for FastAPI BackgroundTasks without a durable worker."""
        await cls(None).process(context)
