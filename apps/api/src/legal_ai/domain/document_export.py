"""Persisted export artifact domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from legal_ai.domain.enums import ExportFormat, ExportStatus


@dataclass
class DocumentExport:
    """Versioned DOCX/PDF artifact metadata."""

    id: UUID
    draft_id: UUID
    draft_version: int
    review_id: UUID
    export_version: int
    format: ExportFormat
    status: ExportStatus
    file_name: str
    source_snapshot_sha256: str
    exported_by: str
    created_at: datetime
    updated_at: datetime
    parent_export_id: UUID | None = None
    storage_path: str | None = None
    content_sha256: str | None = None
    renderer_name: str | None = None
    renderer_version: str | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    def is_downloadable(self) -> bool:
        """Return whether the artifact is publicly downloadable."""
        return self.status in {ExportStatus.GENERATED, ExportStatus.SUPERSEDED}
