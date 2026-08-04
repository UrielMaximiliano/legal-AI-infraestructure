"""SQLAlchemy repository for export attempts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import ExportAttemptModel
from legal_ai.domain.enums import ExportAttemptStatus, ExportFormat
from legal_ai.domain.export_attempt import ExportAttempt


class SQLAlchemyExportAttemptRepository:
    """Attempt history with stable ordering and sanitized metadata mapping."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, attempt_id: UUID) -> ExportAttempt | None:
        result = await self._session.execute(
            select(ExportAttemptModel).where(ExportAttemptModel.id == attempt_id)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_latest(self, export_id: UUID) -> ExportAttempt | None:
        result = await self._session.execute(
            select(ExportAttemptModel)
            .where(ExportAttemptModel.export_id == export_id)
            .order_by(
                ExportAttemptModel.attempt_number.desc(),
                ExportAttemptModel.id.desc(),
            )
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_latest_by_draft_key(
        self,
        draft_id: UUID,
        idempotency_key: str,
        export_format: ExportFormat | None = None,
    ) -> ExportAttempt | None:
        filters = [
            ExportAttemptModel.draft_id == draft_id,
            ExportAttemptModel.idempotency_key == idempotency_key,
        ]
        if export_format is not None:
            filters.append(ExportAttemptModel.format == export_format)
        result = await self._session.execute(
            select(ExportAttemptModel)
            .where(*filters)
            .order_by(
                ExportAttemptModel.created_at.desc(),
                ExportAttemptModel.id.desc(),
            )
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def next_attempt_number(self, export_id: UUID) -> int:
        current = await self._session.scalar(
            select(func.max(ExportAttemptModel.attempt_number)).where(
                ExportAttemptModel.export_id == export_id
            )
        )
        return int(current or 0) + 1

    async def create(self, attempt: ExportAttempt) -> ExportAttempt:
        model = ExportAttemptModel(
            id=attempt.id,
            export_id=attempt.export_id,
            draft_id=attempt.draft_id,
            format=attempt.format,
            idempotency_key=attempt.idempotency_key,
            request_hash=attempt.request_hash,
            attempt_number=attempt.attempt_number,
            status=attempt.status,
            started_at=attempt.started_at,
            completed_at=attempt.completed_at,
            created_at=attempt.created_at,
            updated_at=attempt.updated_at,
            error_code=attempt.error_code,
            error_message=attempt.error_message,
            request_id=attempt.request_id,
            exported_by=attempt.exported_by,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def update(self, attempt: ExportAttempt) -> ExportAttempt:
        result = await self._session.execute(
            update(ExportAttemptModel)
            .where(ExportAttemptModel.id == attempt.id)
            .values(
                status=attempt.status,
                started_at=attempt.started_at,
                completed_at=attempt.completed_at,
                updated_at=attempt.updated_at,
                error_code=attempt.error_code,
                error_message=attempt.error_message,
            )
            .returning(ExportAttemptModel)
        )
        return self._to_domain(result.scalars().one())

    async def list_by_export(
        self, export_id: UUID, offset: int, limit: int
    ) -> tuple[list[ExportAttempt], int]:
        filters = [ExportAttemptModel.export_id == export_id]
        total = await self._session.scalar(
            select(func.count()).select_from(ExportAttemptModel).where(*filters)
        )
        result = await self._session.execute(
            select(ExportAttemptModel)
            .where(*filters)
            .order_by(
                ExportAttemptModel.created_at.desc(), ExportAttemptModel.id.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return [self._to_domain(model) for model in result.scalars().all()], int(
            total or 0
        )

    async def list_for_reconcile(self) -> list[ExportAttempt]:
        """Return all attempts for the bounded manual reconciliation scan."""
        result = await self._session.execute(
            select(ExportAttemptModel).order_by(
                ExportAttemptModel.created_at.asc(), ExportAttemptModel.id.asc()
            )
        )
        return [self._to_domain(model) for model in result.scalars().all()]

    async def delete(self, attempt_id: UUID) -> None:
        """Delete only an explicitly eligible historical failed attempt."""
        await self._session.execute(
            delete(ExportAttemptModel).where(ExportAttemptModel.id == attempt_id)
        )

    @staticmethod
    def _to_domain(model: ExportAttemptModel) -> ExportAttempt:
        return ExportAttempt(
            id=model.id,
            export_id=model.export_id,
            draft_id=model.draft_id,
            format=ExportFormat(model.format),
            idempotency_key=model.idempotency_key,
            request_hash=model.request_hash,
            attempt_number=model.attempt_number,
            status=ExportAttemptStatus(model.status),
            request_id=model.request_id,
            exported_by=model.exported_by,
            created_at=model.created_at,
            started_at=model.started_at,
            completed_at=model.completed_at,
            updated_at=model.updated_at,
            error_code=model.error_code,
            error_message=model.error_message,
        )
