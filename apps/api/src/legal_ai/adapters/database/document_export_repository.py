"""SQLAlchemy repository for export metadata."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import DocumentDraftModel, DocumentExportModel
from legal_ai.domain.document_export import DocumentExport
from legal_ai.domain.enums import ExportFormat, ExportStatus


class SQLAlchemyDocumentExportRepository:
    """Short-lived metadata operations; renderers never use this session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, export_id: UUID) -> DocumentExport | None:
        result = await self._session.execute(
            select(DocumentExportModel).where(DocumentExportModel.id == export_id)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_active(
        self, draft_id: UUID, export_format: ExportFormat
    ) -> DocumentExport | None:
        result = await self._session.execute(
            select(DocumentExportModel).where(
                DocumentExportModel.draft_id == draft_id,
                DocumentExportModel.format == export_format,
                DocumentExportModel.status.in_(
                    [ExportStatus.PENDING, ExportStatus.GENERATING]
                ),
            )
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_current_generated(
        self, draft_id: UUID, export_format: ExportFormat
    ) -> DocumentExport | None:
        result = await self._session.execute(
            select(DocumentExportModel)
            .where(
                DocumentExportModel.draft_id == draft_id,
                DocumentExportModel.format == export_format,
                DocumentExportModel.status == ExportStatus.GENERATED,
            )
            .order_by(
                DocumentExportModel.export_version.desc(),
                DocumentExportModel.id.desc(),
            )
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_by_id_for_update(self, export_id: UUID) -> DocumentExport | None:
        result = await self._session.execute(
            select(DocumentExportModel)
            .where(DocumentExportModel.id == export_id)
            .with_for_update()
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def next_version(self, draft_id: UUID, export_format: ExportFormat) -> int:
        current = await self._session.scalar(
            select(func.max(DocumentExportModel.export_version)).where(
                DocumentExportModel.draft_id == draft_id,
                DocumentExportModel.format == export_format,
            )
        )
        return int(current or 0) + 1

    async def create(self, export: DocumentExport) -> DocumentExport:
        model = DocumentExportModel(
            id=export.id,
            draft_id=export.draft_id,
            draft_version=export.draft_version,
            review_id=export.review_id,
            export_version=export.export_version,
            parent_export_id=export.parent_export_id,
            format=export.format,
            status=export.status,
            storage_path=export.storage_path,
            file_name=export.file_name,
            content_sha256=export.content_sha256,
            source_snapshot_sha256=export.source_snapshot_sha256,
            renderer_name=export.renderer_name,
            renderer_version=export.renderer_version,
            exported_by=export.exported_by,
            created_at=export.created_at,
            updated_at=export.updated_at,
            completed_at=export.completed_at,
            error_code=export.error_code,
            error_message=export.error_message,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def update_status(
        self,
        export_id: UUID,
        status: ExportStatus,
        **values: object,
    ) -> DocumentExport | None:
        values["status"] = status
        result = await self._session.execute(
            update(DocumentExportModel)
            .where(DocumentExportModel.id == export_id)
            .values(**values)
            .returning(DocumentExportModel)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def list_by_draft(
        self,
        draft_id: UUID,
        offset: int,
        limit: int,
        export_format: ExportFormat | None = None,
        draft_version: int | None = None,
        export_version: int | None = None,
        status: ExportStatus | None = None,
    ) -> tuple[list[DocumentExport], int]:
        filters = [DocumentExportModel.draft_id == draft_id]
        if export_format is not None:
            filters.append(DocumentExportModel.format == export_format)
        if draft_version is not None:
            filters.append(DocumentExportModel.draft_version == draft_version)
        if export_version is not None:
            filters.append(DocumentExportModel.export_version == export_version)
        if status is not None:
            filters.append(DocumentExportModel.status == status)
        total = await self._session.scalar(
            select(func.count()).select_from(DocumentExportModel).where(*filters)
        )
        result = await self._session.execute(
            select(DocumentExportModel)
            .where(*filters)
            .order_by(
                DocumentExportModel.created_at.desc(), DocumentExportModel.id.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return [self._to_domain(model) for model in result.scalars().all()], int(
            total or 0
        )

    async def mark_previous_generated(
        self, draft_id: UUID, export_format: ExportFormat, exclude_id: UUID
    ) -> None:
        await self._session.execute(
            update(DocumentExportModel)
            .where(
                DocumentExportModel.draft_id == draft_id,
                DocumentExportModel.format == export_format,
                DocumentExportModel.status == ExportStatus.GENERATED,
                DocumentExportModel.id != exclude_id,
            )
            .values(status=ExportStatus.SUPERSEDED)
        )

    async def list_for_reconcile(
        self,
        draft_id: UUID | None = None,
        export_format: ExportFormat | None = None,
    ) -> list[tuple[DocumentExport, UUID]]:
        """Return export metadata with case ids for the admin scanner."""
        filters = []
        if draft_id is not None:
            filters.append(DocumentExportModel.draft_id == draft_id)
        if export_format is not None:
            filters.append(DocumentExportModel.format == export_format)
        result = await self._session.execute(
            select(DocumentExportModel, DocumentDraftModel.case_file_id)
            .join(
                DocumentDraftModel,
                DocumentDraftModel.id == DocumentExportModel.draft_id,
            )
            .where(*filters)
            .order_by(
                DocumentExportModel.created_at.asc(), DocumentExportModel.id.asc()
            )
        )
        return [
            (self._to_domain(model), case_file_id)
            for model, case_file_id in result.all()
        ]

    @staticmethod
    def _to_domain(model: DocumentExportModel) -> DocumentExport:
        return DocumentExport(
            id=model.id,
            draft_id=model.draft_id,
            draft_version=model.draft_version,
            review_id=model.review_id,
            export_version=model.export_version,
            format=ExportFormat(model.format),
            status=ExportStatus(model.status),
            file_name=model.file_name,
            source_snapshot_sha256=model.source_snapshot_sha256,
            exported_by=model.exported_by,
            created_at=model.created_at,
            updated_at=model.updated_at,
            parent_export_id=model.parent_export_id,
            storage_path=model.storage_path,
            content_sha256=model.content_sha256,
            renderer_name=model.renderer_name,
            renderer_version=model.renderer_version,
            completed_at=model.completed_at,
            error_code=model.error_code,
            error_message=model.error_message,
        )
