"""Template application service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.enums import TemplateDocumentType
from legal_ai.domain.template import Template


class TemplateNotFoundError(Exception):
    """Template not found."""

    def __init__(self, template_id: str) -> None:
        self.template_id = template_id
        super().__init__(f"Template not found: {template_id}")


class TemplateNameConflictError(Exception):
    """Template name already exists for this document type."""

    def __init__(self, name: str, document_type: str) -> None:
        self.name = name
        self.document_type = document_type
        super().__init__(f"Template name conflict: {name} ({document_type})")


class TemplateConflictError(Exception):
    """Template version could not be updated due to a concurrent change."""

    def __init__(self, template_id: str) -> None:
        self.template_id = template_id
        super().__init__(f"Template version conflict: {template_id}")


class TemplateInactiveError(Exception):
    """Template is inactive."""

    def __init__(self, template_id: str) -> None:
        self.template_id = template_id
        super().__init__(f"Template is inactive: {template_id}")


class TemplateService:
    """Service handling template business operations."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def create_template(
        self,
        name: str,
        document_type: TemplateDocumentType,
        body_template: str,
        organ_emisor: str | None = None,
        normativa: str | None = None,
        description: str | None = None,
        variables: list[str] | None = None,
    ) -> Template:
        """Create a new template with version=1."""
        existing = await self._uow.templates.get_active_version(name, document_type)
        if existing:
            raise TemplateNameConflictError(name, document_type)

        template = Template(
            id=uuid.uuid4(),
            name=name,
            document_type=document_type,
            version=1,
            organ_emisor=organ_emisor,
            normativa=normativa,
            description=description,
            body_template=body_template,
            variables=variables or [],
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        return await self._uow.templates.create(template)

    async def get_template(self, template_id: str) -> Template:
        """Get template by ID."""
        template = await self._uow.templates.get_by_id(uuid.UUID(template_id))
        if not template:
            raise TemplateNotFoundError(template_id)
        return template

    async def list_templates(
        self,
        document_type: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Template], int]:
        """List active templates with filters."""
        return await self._uow.templates.list_active(document_type, search, skip, limit)

    async def update_template(
        self,
        template_id: str,
        body_template: str | None = None,
        organ_emisor: str | None = None,
        normativa: str | None = None,
        description: str | None = None,
        variables: list[str] | None = None,
    ) -> Template:
        """Update template. Creates new version if content changes."""
        template = await self._uow.templates.get_by_id(uuid.UUID(template_id))
        if not template:
            raise TemplateNotFoundError(template_id)

        content_changed = False
        if body_template is not None and body_template != template.body_template:
            template.body_template = body_template
            content_changed = True
        if variables is not None and variables != template.variables:
            template.variables = variables
            content_changed = True

        if organ_emisor is not None:
            template.organ_emisor = organ_emisor
        if normativa is not None:
            template.normativa = normativa
        if description is not None:
            template.description = description

        if content_changed:
            # Deactivate all versions of this name+type
            await self._uow.templates.deactivate_all_versions(
                template.name, template.document_type
            )
            # Create new version
            new_template = Template(
                id=uuid.uuid4(),
                name=template.name,
                document_type=template.document_type,
                version=template.version + 1,
                organ_emisor=template.organ_emisor,
                normativa=template.normativa,
                description=template.description,
                body_template=template.body_template,
                variables=template.variables,
                is_active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            return await self._uow.templates.create(new_template)

        template.updated_at = datetime.now(UTC)
        return await self._uow.templates.update(template)

    async def deactivate_template(self, template_id: str) -> Template:
        """Deactivate a template."""
        template = await self._uow.templates.get_by_id(uuid.UUID(template_id))
        if not template:
            raise TemplateNotFoundError(template_id)

        if not template.is_active:
            raise TemplateInactiveError(template_id)

        await self._uow.templates.deactivate_all_versions(
            template.name, template.document_type
        )
        template.is_active = False
        template.updated_at = datetime.now(UTC)
        return await self._uow.templates.update(template)

    async def get_active_version(
        self, name: str, document_type: str
    ) -> Template | None:
        """Get active version of a template."""
        return await self._uow.templates.get_active_version(name, document_type)
