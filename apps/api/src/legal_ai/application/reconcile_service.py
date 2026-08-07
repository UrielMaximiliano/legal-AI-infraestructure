"""Manual, auditable reconciliation for export metadata and local files."""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, cast
from uuid import UUID, uuid4

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage
from legal_ai.application.artifact_integrity import (
    DOCX_MIME,
    PDF_MIME,
    ArtifactIntegrityValidator,
)
from legal_ai.config import settings
from legal_ai.domain.enums import ExportAttemptStatus, ExportFormat, ExportStatus
from legal_ai.domain.errors import (
    CleanupConflictError,
    DomainError,
    FilesystemError,
    ValidationDomainError,
)
from legal_ai.domain.review_event import ReviewEvent
from legal_ai.observability.logging import log_event
from legal_ai.schemas.validation import validate_actor

INCIDENT_TYPES = {
    "TEMPORARY_FILE",
    "ORPHAN_FILE",
    "FAILED_ATTEMPT",
    "MISSING_FILE",
    "CORRUPT_FILE",
    "INCOMPLETE_DB",
}


@dataclass(frozen=True)
class ReconcileFilters:
    """Normalized filters used for deterministic run idempotency."""

    case_file_id: UUID | None = None
    draft_id: UUID | None = None
    format: ExportFormat | None = None
    incident_type: str | None = None
    older_than: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "case_file_id": str(self.case_file_id) if self.case_file_id else None,
            "draft_id": str(self.draft_id) if self.draft_id else None,
            "format": self.format.value if self.format else None,
            "incident_type": self.incident_type,
            "older_than": self.older_than,
        }


class ReconcileService:
    """Detect and optionally remove only explicitly eligible resources."""

    def __init__(
        self,
        uow: UnitOfWork,
        *,
        storage: LocalArtifactStorage | None = None,
        integrity: ArtifactIntegrityValidator | None = None,
        now: datetime | None = None,
    ) -> None:
        self._uow = uow
        self._storage = storage or LocalArtifactStorage()
        self._integrity = integrity or ArtifactIntegrityValidator()
        self._now = (now or datetime.now(UTC)).astimezone(UTC)

    async def reconcile(
        self,
        *,
        actor: str,
        run_id: UUID | None = None,
        execute: bool = False,
        case_file_id: UUID | None = None,
        draft_id: UUID | None = None,
        format: str | None = None,  # noqa: A002
        incident_type: str | None = None,
        older_than: str | None = None,
    ) -> dict[str, Any]:
        """Run one idempotent reconciliation scan and return its JSON shape."""
        started = time.perf_counter()
        normalized_actor = self._actor(actor)
        filters = self._filters(
            case_file_id,
            draft_id,
            format,
            incident_type,
            older_than,
        )
        run = run_id or uuid4()
        filters_hash = self.filters_hash(filters, normalized_actor, execute)
        previous = await self._uow.review_events.get_reconciliation_run(run)
        if previous is not None:
            previous_hash = (previous.summary or {}).get("_filters_hash")
            if previous_hash != filters_hash:
                raise CleanupConflictError()
            return self._public_summary(previous.summary or {})

        items: list[dict[str, Any]] = []
        counters = {"deleted": 0, "omitted": 0, "conflicts": 0, "errors": 0}
        files = self._scan_files()
        exports = await self._list_exports(filters)
        export_by_path = {
            export.storage_path: (export, case_id)
            for export, case_id in exports
            if export.storage_path
        }
        attempts = await self._list_attempts()
        attempts_by_export: dict[UUID, list[Any]] = defaultdict(list)
        for attempt in attempts:
            attempts_by_export[attempt.export_id].append(attempt)

        await self._detect_export_incidents(
            exports,
            attempts_by_export,
            filters,
            normalized_actor,
            run,
            items,
            counters,
        )
        await self._detect_attempt_incidents(
            exports,
            attempts_by_export,
            filters,
            normalized_actor,
            run,
            execute,
            items,
            counters,
        )
        await self._detect_file_incidents(
            files,
            export_by_path,
            exports,
            filters,
            normalized_actor,
            run,
            execute,
            items,
            counters,
        )

        result: dict[str, Any] = {
            "run_id": str(run),
            "mode": "execute" if execute else "dry-run",
            "filters": filters.as_dict(),
            "candidates": len(items),
            **counters,
            "items": items,
            "_filters_hash": filters_hash,
        }
        log_event(
            "reconcile_completed",
            run_id=run,
            phase="reconcile",
            operation="document-exports reconcile",
            candidates=len(items),
            deleted=counters["deleted"],
            omitted=counters["omitted"],
            conflicts=counters["conflicts"],
            errors=counters["errors"],
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            result="success",
        )
        await self._uow.review_events.create(
            ReviewEvent(
                id=uuid4(),
                resource_type="RECONCILIATION",
                event_type="RECONCILIATION_RUN",
                run_id=run,
                actor=normalized_actor,
                resource_id=str(run),
                created_at=self._now,
                summary=result,
            )
        )
        return self._public_summary(result)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        """Compatibility alias for callers that name the operation ``run``."""
        return await self.reconcile(**kwargs)

    @staticmethod
    def filters_hash(filters: ReconcileFilters, actor: str, execute: bool) -> str:
        payload = {
            "actor": actor,
            "execute": execute,
            "filters": filters.as_dict(),
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    async def _list_exports(self, filters: ReconcileFilters) -> list[tuple[Any, UUID]]:
        repository = self._uow.document_exports
        method = getattr(repository, "list_for_reconcile", None)
        if method is None:
            return []
        result = await method(filters.draft_id, filters.format)
        return cast("list[tuple[Any, UUID]]", result)

    async def _list_attempts(self) -> list[Any]:
        method = getattr(self._uow.export_attempts, "list_for_reconcile", None)
        if method is None:
            return []
        result = await method()
        return cast("list[Any]", result)

    def _scan_files(self) -> list[tuple[str, int, float]]:
        if not self._storage.health():
            raise FilesystemError()
        return self._storage.scan_files()

    async def _detect_export_incidents(
        self,
        exports: list[tuple[Any, UUID]],
        attempts_by_export: dict[UUID, list[Any]],
        filters: ReconcileFilters,
        actor: str,
        run: UUID,
        items: list[dict[str, Any]],
        counters: dict[str, int],
    ) -> None:
        for export, case_id in exports:
            if not self._matches_export(export, case_id, filters):
                continue
            attempts = attempts_by_export.get(export.id, [])
            has_processing = any(
                item.status
                in {ExportAttemptStatus.PENDING, ExportAttemptStatus.PROCESSING}
                for item in attempts
            )
            has_succeeded_attempt = any(
                item.status == ExportAttemptStatus.SUCCEEDED for item in attempts
            )
            if has_succeeded_attempt and export.status not in {
                ExportStatus.GENERATED,
                ExportStatus.SUPERSEDED,
            }:
                if self._incident_allowed(filters, "INCOMPLETE_DB"):
                    await self._record_item(
                        "INCOMPLETE_DB",
                        str(export.id),
                        "omit",
                        "succeeded attempt has no downloadable export",
                        actor,
                        run,
                        items,
                        counters,
                    )
                continue
            if export.status in {ExportStatus.PENDING, ExportStatus.GENERATING}:
                if not self._incident_allowed(filters, "INCOMPLETE_DB"):
                    continue
                await self._record_item(
                    "INCOMPLETE_DB",
                    str(export.id),
                    "omit",
                    "export remains active",
                    actor,
                    run,
                    items,
                    counters,
                )
                continue
            if export.status not in {
                ExportStatus.GENERATED,
                ExportStatus.SUPERSEDED,
            }:
                continue
            if not export.storage_path or not self._safe_exists(export.storage_path):
                if not self._incident_allowed(filters, "MISSING_FILE"):
                    continue
                if not self._older_than_filter(export.created_at, filters):
                    continue
                await self._record_item(
                    "MISSING_FILE",
                    str(export.id),
                    "omit",
                    "downloadable export has no file",
                    actor,
                    run,
                    items,
                    counters,
                )
                continue
            try:
                expected = export.content_sha256
                if export.format == ExportFormat.PDF:
                    self._integrity.validate_pdf(
                        self._storage.resolve_relative(export.storage_path),
                        expected_sha256=expected,
                        declared_mime=PDF_MIME,
                    )
                else:
                    self._integrity.validate_docx(
                        self._storage.resolve_relative(export.storage_path),
                        expected_sha256=expected,
                        declared_mime=DOCX_MIME,
                    )
            except Exception:
                if not self._incident_allowed(filters, "CORRUPT_FILE"):
                    continue
                if not self._older_than_filter(export.created_at, filters):
                    continue
                await self._record_item(
                    "CORRUPT_FILE",
                    str(export.id),
                    "omit",
                    "integrity validation failed",
                    actor,
                    run,
                    items,
                    counters,
                )
            if has_processing and export.storage_path:
                continue

    async def _detect_attempt_incidents(
        self,
        exports: list[tuple[Any, UUID]],
        attempts_by_export: dict[UUID, list[Any]],
        filters: ReconcileFilters,
        actor: str,
        run: UUID,
        execute: bool,
        items: list[dict[str, Any]],
        counters: dict[str, int],
    ) -> None:
        export_lookup = {export.id: (export, case_id) for export, case_id in exports}
        cutoff = self._now - timedelta(
            days=settings.export.failed_attempt_retention_days
        )
        for export_id, attempts in attempts_by_export.items():
            export_data = export_lookup.get(export_id)
            if export_data is None:
                continue
            export, case_id = export_data
            if not self._matches_export(export, case_id, filters):
                continue
            latest_number = max((item.attempt_number for item in attempts), default=0)
            for attempt in attempts:
                if attempt.status != ExportAttemptStatus.FAILED:
                    continue
                if not self._incident_allowed(filters, "FAILED_ATTEMPT"):
                    continue
                if attempt.attempt_number >= latest_number:
                    await self._record_item(
                        "FAILED_ATTEMPT",
                        str(attempt.id),
                        "omit",
                        "latest attempt is retained",
                        actor,
                        run,
                        items,
                        counters,
                    )
                    continue
                if attempt.created_at > cutoff or not self._older_than_filter(
                    attempt.created_at, filters
                ):
                    continue
                action = "delete" if execute else "would_delete"
                try:
                    if execute:
                        await self._uow.export_attempts.delete(attempt.id)
                    await self._record_item(
                        "FAILED_ATTEMPT",
                        str(attempt.id),
                        action,
                        "failed attempt is outside retention",
                        actor,
                        run,
                        items,
                        counters,
                        deleted=execute,
                    )
                except Exception:
                    await self._record_item(
                        "FAILED_ATTEMPT",
                        str(attempt.id),
                        "error",
                        "failed attempt could not be removed",
                        actor,
                        run,
                        items,
                        counters,
                    )

    async def _detect_file_incidents(
        self,
        files: list[tuple[str, int, float]],
        export_by_path: dict[str | None, tuple[Any, UUID]],
        exports: list[tuple[Any, UUID]],
        filters: ReconcileFilters,
        actor: str,
        run: UUID,
        execute: bool,
        items: list[dict[str, Any]],
        counters: dict[str, int],
    ) -> None:
        known_paths = {path for path in export_by_path if path}
        processing_keys = {
            (str(export.draft_id), export.format.value.lower())
            for export, _ in exports
            if export.status in {ExportStatus.PENDING, ExportStatus.GENERATING}
        }
        for relative, _size, modified in files:
            if relative in known_paths:
                continue
            path = PurePosixPath(relative)
            incident = (
                "TEMPORARY_FILE" if path.name.startswith("tmp-") else "ORPHAN_FILE"
            )
            if not self._incident_allowed(filters, incident):
                continue
            if not self._matches_file(path, filters):
                continue
            created_at = datetime.fromtimestamp(modified, UTC)
            if incident == "TEMPORARY_FILE":
                eligible = self._older_than_filter(
                    created_at,
                    filters,
                    default_age=timedelta(hours=settings.export.temp_retention_hours),
                )
            else:
                fingerprint = self._fingerprint(relative)
                first = await self._uow.review_events.get_orphan_detection(fingerprint)
                if first is None:
                    await self._uow.review_events.create(
                        ReviewEvent(
                            id=uuid4(),
                            resource_type="ORPHAN_FILE",
                            event_type="ORPHAN_DETECTED",
                            resource_id=fingerprint,
                            actor=actor,
                            run_id=run,
                            created_at=self._now,
                            summary={"incident_type": incident},
                        )
                    )
                    detected_at = self._now
                else:
                    detected_at = first.created_at
                eligible = self._older_than_filter(
                    detected_at,
                    filters,
                    default_age=timedelta(days=settings.export.orphan_retention_days),
                )
            if not eligible:
                continue
            if self._file_has_processing_export(path, processing_keys):
                await self._record_item(
                    incident,
                    self._fingerprint(relative),
                    "omit",
                    "processing attempt is active",
                    actor,
                    run,
                    items,
                    counters,
                )
                continue
            action = "delete" if execute else "would_delete"
            try:
                if execute:
                    self._storage.delete_scanned(relative)
                await self._record_item(
                    incident,
                    self._fingerprint(relative),
                    action,
                    "eligible by retention policy",
                    actor,
                    run,
                    items,
                    counters,
                    deleted=execute,
                )
            except Exception:
                await self._record_item(
                    incident,
                    self._fingerprint(relative),
                    "error",
                    "file could not be removed",
                    actor,
                    run,
                    items,
                    counters,
                )

    async def _record_item(
        self,
        incident: str,
        resource_id: str,
        action: str,
        reason: str,
        actor: str,
        run: UUID,
        items: list[dict[str, Any]],
        counters: dict[str, int],
        *,
        deleted: bool = False,
    ) -> None:
        if action == "omit":
            counters["omitted"] += 1
        elif action == "error":
            counters["errors"] += 1
        elif not deleted:
            counters["conflicts"] += 0
        if deleted:
            counters["deleted"] += 1
        item = {
            "incident_type": incident,
            "resource_type": "artifact" if incident.endswith("FILE") else "attempt",
            "resource_id": resource_id,
            "action": action,
            "reason": reason,
        }
        log_event(
            "reconcile_action",
            run_id=run,
            resource_type=incident,
            action=action,
            result="deleted" if deleted else action,
            operation="document-exports reconcile",
        )
        items.append(item)
        await self._uow.review_events.create(
            ReviewEvent(
                id=uuid4(),
                resource_type=incident,
                event_type="RECONCILIATION_ACTION",
                resource_id=resource_id,
                actor=actor,
                run_id=run,
                created_at=self._now,
                summary={"incident_type": incident, "action": action, "reason": reason},
            )
        )

    def _safe_exists(self, relative_path: str) -> bool:
        try:
            return self._storage.exists(relative_path)
        except DomainError:
            return False

    @staticmethod
    def _fingerprint(relative_path: str) -> str:
        return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()

    @staticmethod
    def _actor(value: str) -> str:
        try:
            result = validate_actor(value)
        except ValueError as exc:
            raise ValidationDomainError(details={"field": "actor"}) from exc
        if result is None:
            raise ValidationDomainError(details={"field": "actor"})
        return result

    @staticmethod
    def _filters(
        case_file_id: UUID | None,
        draft_id: UUID | None,
        format: str | None,  # noqa: A002
        incident_type: str | None,
        older_than: str | None,
    ) -> ReconcileFilters:
        normalized_format = None
        if format is not None:
            try:
                normalized_format = ExportFormat(format.upper())
            except ValueError as exc:
                raise ValidationDomainError(details={"field": "format"}) from exc
        normalized_incident = incident_type.upper() if incident_type else None
        if normalized_incident and normalized_incident not in INCIDENT_TYPES:
            raise ValidationDomainError(details={"field": "incident_type"})
        if older_than is not None:
            ReconcileService._parse_older_than(older_than)
        return ReconcileFilters(
            case_file_id=case_file_id,
            draft_id=draft_id,
            format=normalized_format,
            incident_type=normalized_incident,
            older_than=older_than,
        )

    @staticmethod
    def _parse_older_than(value: str) -> datetime | timedelta:
        if value.startswith("P"):
            if value.endswith("H"):
                return timedelta(hours=int(value[1:-1]))
            if value.endswith("D"):
                return timedelta(days=int(value[1:-1]))
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except (ValueError, TypeError) as exc:
            raise ValidationDomainError(details={"field": "older_than"}) from exc

    def _older_than_filter(
        self,
        created_at: datetime,
        filters: ReconcileFilters,
        *,
        default_age: timedelta = timedelta(0),
    ) -> bool:
        value = (
            self._parse_older_than(filters.older_than) if filters.older_than else None
        )
        if isinstance(value, datetime):
            return created_at <= value and self._now - created_at >= default_age
        age = value if isinstance(value, timedelta) else default_age
        return self._now - created_at >= max(default_age, age)

    @staticmethod
    def _incident_allowed(filters: ReconcileFilters, incident: str) -> bool:
        return filters.incident_type is None or filters.incident_type == incident

    @staticmethod
    def _matches_export(export: Any, case_id: UUID, filters: ReconcileFilters) -> bool:
        return not (
            (filters.case_file_id is not None and case_id != filters.case_file_id)
            or (filters.draft_id is not None and export.draft_id != filters.draft_id)
            or (filters.format is not None and export.format != filters.format)
        )

    @staticmethod
    def _matches_file(path: PurePosixPath, filters: ReconcileFilters) -> bool:
        parts = path.parts
        if len(parts) < 3:
            return (
                filters.case_file_id is None
                and filters.draft_id is None
                and filters.format is None
            )
        if filters.case_file_id is not None and parts[0] != str(filters.case_file_id):
            return False
        if filters.draft_id is not None and parts[1] != str(filters.draft_id):
            return False
        return filters.format is None or parts[2] == filters.format.value.lower()

    @staticmethod
    def _file_has_processing_export(
        path: PurePosixPath, processing_keys: set[tuple[str, str]]
    ) -> bool:
        return (
            len(path.parts) >= 3
            and (
                path.parts[1],
                path.parts[2],
            )
            in processing_keys
        )

    @staticmethod
    def _public_summary(summary: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in summary.items() if not key.startswith("_")}
