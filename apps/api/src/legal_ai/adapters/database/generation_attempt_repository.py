"""SQLAlchemy generation attempt repository implementation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import GenerationAttemptModel
from legal_ai.domain.enums import GenerationStatus
from legal_ai.domain.generation_attempt import GenerationAttempt


class SQLAlchemyGenerationAttemptRepository:
    """SQLAlchemy implementation of generation attempt repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, attempt: GenerationAttempt) -> GenerationAttempt:
        model = GenerationAttemptModel(
            id=attempt.id,
            case_file_id=attempt.case_file_id,
            template_id=attempt.template_id,
            idempotency_key=attempt.idempotency_key,
            model=attempt.model,
            prompt_hash=attempt.prompt_hash,
            prompt_content=attempt.prompt_content,
            status=attempt.status,
            started_at=attempt.started_at,
            completed_at=attempt.completed_at,
            error_code=attempt.error_code,
            error_message=attempt.error_message,
            created_at=attempt.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get_by_idempotency_key(self, key: str) -> GenerationAttempt | None:
        result = await self._session.execute(
            select(GenerationAttemptModel).where(
                GenerationAttemptModel.idempotency_key == key
            )
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_by_id(self, attempt_id: UUID) -> GenerationAttempt | None:
        result = await self._session.execute(
            select(GenerationAttemptModel).where(
                GenerationAttemptModel.id == attempt_id
            )
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def list_by_case_file(self, case_file_id: UUID) -> list[GenerationAttempt]:
        result = await self._session.execute(
            select(GenerationAttemptModel)
            .where(GenerationAttemptModel.case_file_id == case_file_id)
            .order_by(GenerationAttemptModel.created_at.desc())
        )
        models = result.scalars().all()
        return [self._to_domain(m) for m in models]

    async def update(self, attempt: GenerationAttempt) -> GenerationAttempt:
        await self._session.execute(
            update(GenerationAttemptModel)
            .where(GenerationAttemptModel.id == attempt.id)
            .values(
                status=attempt.status,
                completed_at=attempt.completed_at,
                error_code=attempt.error_code,
                error_message=attempt.error_message,
            )
            .returning(GenerationAttemptModel)
        )
        await self._session.flush()
        result2 = await self._session.execute(
            select(GenerationAttemptModel).where(
                GenerationAttemptModel.id == attempt.id
            )
        )
        model = result2.scalars().one()
        return self._to_domain(model)

    async def delete_by_idempotency_key(self, key: str) -> None:
        await self._session.execute(
            delete(GenerationAttemptModel).where(
                GenerationAttemptModel.idempotency_key == key
            )
        )
        await self._session.flush()

    async def cleanup_expired(self, window_hours: int = 24) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        result = await self._session.execute(
            delete(GenerationAttemptModel)
            .where(GenerationAttemptModel.created_at < cutoff)
            .returning(GenerationAttemptModel.id)
        )
        await self._session.flush()
        return len(result.scalars().all())

    @staticmethod
    def _to_domain(model: GenerationAttemptModel) -> GenerationAttempt:
        return GenerationAttempt(
            id=model.id,
            case_file_id=model.case_file_id,
            template_id=model.template_id,
            idempotency_key=model.idempotency_key,
            model=model.model,
            prompt_hash=model.prompt_hash,
            prompt_content=model.prompt_content,
            status=GenerationStatus(model.status),
            started_at=model.started_at,
            completed_at=model.completed_at,
            error_code=model.error_code,
            error_message=model.error_message,
            created_at=model.created_at,
        )
