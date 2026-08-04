"""SQLAlchemy draft repository implementation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import DocumentDraftModel
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus


class SQLAlchemyDraftRepository:
    """SQLAlchemy implementation of draft repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, draft: Draft) -> Draft:
        model = DocumentDraftModel(
            id=draft.id,
            template_id=draft.template_id,
            case_file_id=draft.case_file_id,
            title=draft.title,
            content=draft.content,
            status=draft.status,
            version=draft.version,
            generation_number=draft.generation_number,
            context_snapshot=draft.context_snapshot,
            context_hash=draft.context_hash,
            variables_used=draft.variables_used,
            parent_draft_id=draft.parent_draft_id,
            observations=draft.observations,
            request_id=draft.request_id,
            finalized_by=draft.finalized_by,
            finalized_at=draft.finalized_at,
            finalization_notes=draft.finalization_notes,
            final_snapshot=draft.final_snapshot,
            final_snapshot_sha256=draft.final_snapshot_sha256,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get_by_id(self, draft_id: UUID) -> Draft | None:
        result = await self._session.execute(
            select(DocumentDraftModel).where(DocumentDraftModel.id == draft_id)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_by_id_for_update(self, draft_id: UUID) -> Draft | None:
        """Load one draft with a short row lock for finalization."""
        result = await self._session.execute(
            select(DocumentDraftModel)
            .where(DocumentDraftModel.id == draft_id)
            .with_for_update()
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def list_by_case_file(
        self,
        case_file_id: UUID,
        status: str | None,
        skip: int,
        limit: int,
    ) -> tuple[list[Draft], int]:
        filters = [DocumentDraftModel.case_file_id == case_file_id]

        if status:
            filters.append(DocumentDraftModel.status == status)

        query = select(DocumentDraftModel).where(*filters)
        count_query = (
            select(func.count()).select_from(DocumentDraftModel).where(*filters)
        )

        total_result = await self._session.execute(count_query)
        total = total_result.scalar() or 0

        query = (
            query.order_by(DocumentDraftModel.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_domain(m) for m in models], total

    async def update_with_optimistic_lock(
        self, draft: Draft, expected_version: int
    ) -> Draft | None:
        result = await self._session.execute(
            update(DocumentDraftModel)
            .where(
                DocumentDraftModel.id == draft.id,
                DocumentDraftModel.version == expected_version,
                DocumentDraftModel.finalized_at.is_(None),
            )
            .values(
                content=draft.content,
                version=draft.version + 1,
                observations=draft.observations,
            )
            .returning(DocumentDraftModel)
        )
        row = result.first()
        if not row:
            return None
        # Re-fetch the updated model
        result2 = await self._session.execute(
            select(DocumentDraftModel).where(DocumentDraftModel.id == draft.id)
        )
        model = result2.scalars().one()
        return self._to_domain(model)

    async def update(self, draft: Draft, expected_version: int) -> Draft | None:
        """Persist all mutable fields while enforcing optimistic locking."""
        result = await self._session.execute(
            update(DocumentDraftModel)
            .where(
                DocumentDraftModel.id == draft.id,
                DocumentDraftModel.version == expected_version,
                DocumentDraftModel.finalized_at.is_(None),
            )
            .values(
                title=draft.title,
                content=draft.content,
                status=draft.status,
                version=expected_version + 1,
                observations=draft.observations,
            )
            .returning(DocumentDraftModel)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def update_status(
        self, draft_id: UUID, new_status: DraftStatus, version: int
    ) -> Draft | None:
        result = await self._session.execute(
            update(DocumentDraftModel)
            .where(
                DocumentDraftModel.id == draft_id,
                DocumentDraftModel.version == version,
                DocumentDraftModel.finalized_at.is_(None),
            )
            .values(
                status=new_status,
                version=version + 1,
            )
            .returning(DocumentDraftModel)
        )
        row = result.first()
        if not row:
            return None
        result2 = await self._session.execute(
            select(DocumentDraftModel).where(DocumentDraftModel.id == draft_id)
        )
        model = result2.scalars().one()
        return self._to_domain(model)

    async def update_finalization(
        self,
        draft_id: UUID,
        expected_version: int,
        finalized_by: str,
        finalized_at: object,
        finalization_notes: str | None,
        final_snapshot: dict[str, object],
        final_snapshot_sha256: str,
    ) -> Draft | None:
        """Write finalization metadata exactly once under optimistic locking."""
        result = await self._session.execute(
            update(DocumentDraftModel)
            .where(
                DocumentDraftModel.id == draft_id,
                DocumentDraftModel.version == expected_version,
                DocumentDraftModel.finalized_at.is_(None),
            )
            .values(
                finalized_by=finalized_by,
                finalized_at=finalized_at,
                finalization_notes=finalization_notes,
                final_snapshot=final_snapshot,
                final_snapshot_sha256=final_snapshot_sha256,
                version=expected_version + 1,
            )
            .returning(DocumentDraftModel)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    @staticmethod
    def _to_domain(model: DocumentDraftModel) -> Draft:
        return Draft(
            id=model.id,
            template_id=model.template_id,
            case_file_id=model.case_file_id,
            title=model.title,
            content=model.content,
            status=DraftStatus(model.status),
            version=model.version,
            generation_number=model.generation_number,
            context_snapshot=model.context_snapshot,
            context_hash=model.context_hash,
            variables_used=model.variables_used or {},
            parent_draft_id=model.parent_draft_id,
            observations=model.observations,
            request_id=model.request_id,
            finalized_by=model.finalized_by,
            finalized_at=model.finalized_at,
            finalization_notes=model.finalization_notes,
            final_snapshot=model.final_snapshot,
            final_snapshot_sha256=model.final_snapshot_sha256,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
