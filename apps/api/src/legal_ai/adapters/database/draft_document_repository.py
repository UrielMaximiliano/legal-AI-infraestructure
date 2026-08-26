"""Persistence for immutable structured document versions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import DraftDocumentVersionModel
from legal_ai.domain.draft_document import DraftDocumentVersion


class SQLAlchemyDraftDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, value: DraftDocumentVersion) -> DraftDocumentVersion:
        source = {
            "ai": "AI_GENERATED",
            "ai_generated": "AI_GENERATED",
            "manual": "MANUAL",
            "human": "HUMAN_EDIT",
            "human_edit": "HUMAN_EDIT",
        }.get(value.source.lower(), value.source.upper())
        model = DraftDocumentVersionModel(
            id=value.id,
            draft_id=value.draft_id,
            version=value.version,
            document=value.document,
            content=value.content,
            content_sha256=value.content_sha256,
            source=source,
            edited_by=value.edited_by,
            created_at=value.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get_current(self, draft_id: UUID) -> DraftDocumentVersion | None:
        result = await self._session.execute(
            select(DraftDocumentVersionModel)
            .where(DraftDocumentVersionModel.draft_id == draft_id)
            .order_by(DraftDocumentVersionModel.version.desc())
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def list_by_draft(self, draft_id: UUID) -> list[DraftDocumentVersion]:
        result = await self._session.execute(
            select(DraftDocumentVersionModel)
            .where(DraftDocumentVersionModel.draft_id == draft_id)
            .order_by(DraftDocumentVersionModel.version.desc())
        )
        return [self._to_domain(model) for model in result.scalars().all()]

    @staticmethod
    def _to_domain(model: DraftDocumentVersionModel) -> DraftDocumentVersion:
        return DraftDocumentVersion(
            id=model.id,
            draft_id=model.draft_id,
            version=model.version,
            document=dict(model.document),
            content=model.content,
            content_sha256=model.content_sha256,
            source=model.source,
            edited_by=model.edited_by,
            created_at=model.created_at,
        )


# Explicit name kept for adapters that use the version-oriented vocabulary.
SQLAlchemyDraftDocumentVersionRepository = SQLAlchemyDraftDocumentRepository
