"""Persistence for unique official document identifiers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import OfficialDocumentIdentifierModel
from legal_ai.domain.official_document import OfficialDocumentIdentifier


class SQLAlchemyOfficialDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, identifier: OfficialDocumentIdentifier
    ) -> OfficialDocumentIdentifier:
        model = OfficialDocumentIdentifierModel(
            id=identifier.id,
            draft_id=identifier.draft_id,
            document_type=identifier.document_type,
            number=identifier.number,
            year=identifier.year,
            issued_on=identifier.issued_on,
            created_at=identifier.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get_by_draft(self, draft_id: UUID) -> OfficialDocumentIdentifier | None:
        result = await self._session.execute(
            select(OfficialDocumentIdentifierModel).where(
                OfficialDocumentIdentifierModel.draft_id == draft_id
            )
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_by_identity(
        self, document_type: str, number: int, year: int
    ) -> OfficialDocumentIdentifier | None:
        result = await self._session.execute(
            select(OfficialDocumentIdentifierModel).where(
                OfficialDocumentIdentifierModel.document_type == document_type,
                OfficialDocumentIdentifierModel.number == number,
                OfficialDocumentIdentifierModel.year == year,
            )
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    @staticmethod
    def _to_domain(
        model: OfficialDocumentIdentifierModel,
    ) -> OfficialDocumentIdentifier:
        return OfficialDocumentIdentifier(
            id=model.id,
            draft_id=model.draft_id,
            document_type=model.document_type,
            number=model.number,
            year=model.year,
            issued_on=model.issued_on,
            created_at=model.created_at,
        )
