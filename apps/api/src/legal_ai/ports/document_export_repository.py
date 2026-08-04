"""Ports for export metadata and short Tx1/Tx2 transitions."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.document_export import DocumentExport
from legal_ai.domain.enums import ExportFormat, ExportStatus


class DocumentExportRepository(Protocol):
    async def get_by_id(self, export_id: UUID) -> DocumentExport | None: ...

    async def get_active(
        self, draft_id: UUID, export_format: ExportFormat
    ) -> DocumentExport | None: ...

    async def get_current_generated(
        self, draft_id: UUID, export_format: ExportFormat
    ) -> DocumentExport | None: ...

    async def get_by_id_for_update(self, export_id: UUID) -> DocumentExport | None: ...

    async def next_version(
        self, draft_id: UUID, export_format: ExportFormat
    ) -> int: ...

    async def create(self, export: DocumentExport) -> DocumentExport: ...

    async def update_status(
        self,
        export_id: UUID,
        status: ExportStatus,
        **values: object,
    ) -> DocumentExport | None: ...

    async def list_by_draft(
        self,
        draft_id: UUID,
        offset: int,
        limit: int,
        export_format: ExportFormat | None = None,
        draft_version: int | None = None,
        export_version: int | None = None,
        status: ExportStatus | None = None,
    ) -> tuple[list[DocumentExport], int]: ...

    async def mark_previous_generated(
        self, draft_id: UUID, export_format: ExportFormat, exclude_id: UUID
    ) -> None: ...

    async def list_for_reconcile(
        self,
        draft_id: UUID | None = None,
        export_format: ExportFormat | None = None,
    ) -> list[tuple[DocumentExport, UUID]]: ...
