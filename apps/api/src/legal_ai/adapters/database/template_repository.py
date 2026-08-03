"""SQLAlchemy template repository implementation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from legal_ai.adapters.database.models import DocumentTemplateModel
from legal_ai.domain.enums import TemplateDocumentType
from legal_ai.domain.template import Template


class SQLAlchemyTemplateRepository:
    """SQLAlchemy implementation of template repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, template: Template) -> Template:
        model = DocumentTemplateModel(
            id=template.id,
            name=template.name,
            document_type=template.document_type,
            version=template.version,
            organ_emisor=template.organ_emisor,
            normativa=template.normativa,
            description=template.description,
            body_template=template.body_template,
            variables=template.variables,
            is_active=template.is_active,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get_by_id(self, template_id: UUID) -> Template | None:
        result = await self._session.execute(
            select(DocumentTemplateModel).where(DocumentTemplateModel.id == template_id)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_active_version(
        self, name: str, document_type: str
    ) -> Template | None:
        result = await self._session.execute(
            select(DocumentTemplateModel)
            .where(
                DocumentTemplateModel.name == name,
                DocumentTemplateModel.document_type == document_type,
                DocumentTemplateModel.is_active == True,  # noqa: E712
            )
            .order_by(DocumentTemplateModel.version.desc())
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def list_active(
        self,
        document_type: str | None,
        search: str | None,
        skip: int,
        limit: int,
    ) -> tuple[list[Template], int]:
        filters: list[ColumnElement[bool]] = [DocumentTemplateModel.is_active.is_(True)]

        if document_type:
            filters.append(DocumentTemplateModel.document_type == document_type)

        if search:
            filters.append(DocumentTemplateModel.name.ilike(f"%{search}%"))

        query = select(DocumentTemplateModel).where(*filters)
        count_query = (
            select(func.count()).select_from(DocumentTemplateModel).where(*filters)
        )

        total_result = await self._session.execute(count_query)
        total = total_result.scalar() or 0

        query = (
            query.order_by(
                DocumentTemplateModel.created_at.desc(),
                DocumentTemplateModel.id.desc(),
            )
            .offset(skip)
            .limit(limit)
        )

        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_domain(m) for m in models], total

    async def update(self, template: Template) -> Template:
        result = await self._session.execute(
            select(DocumentTemplateModel).where(DocumentTemplateModel.id == template.id)
        )
        model = result.scalars().one()
        model.name = template.name
        model.document_type = template.document_type
        model.version = template.version
        model.organ_emisor = template.organ_emisor
        model.normativa = template.normativa
        model.description = template.description
        model.body_template = template.body_template
        model.variables = template.variables
        model.is_active = template.is_active
        await self._session.flush()
        return self._to_domain(model)

    async def deactivate_all_versions(self, name: str, document_type: str) -> None:
        result = await self._session.execute(
            select(DocumentTemplateModel).where(
                DocumentTemplateModel.name == name,
                DocumentTemplateModel.document_type == document_type,
                DocumentTemplateModel.is_active == True,  # noqa: E712
            )
        )
        models = result.scalars().all()
        for model in models:
            model.is_active = False
        await self._session.flush()

    @staticmethod
    def _to_domain(model: DocumentTemplateModel) -> Template:
        return Template(
            id=model.id,
            name=model.name,
            document_type=TemplateDocumentType(model.document_type),
            version=model.version,
            organ_emisor=model.organ_emisor,
            normativa=model.normativa,
            description=model.description,
            body_template=model.body_template,
            variables=model.variables or [],
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
