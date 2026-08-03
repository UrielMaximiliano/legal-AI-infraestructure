"""Unit tests for template service."""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from legal_ai.application.template_service import (
    TemplateInactiveError,
    TemplateNameConflictError,
    TemplateNotFoundError,
    TemplateService,
)
from legal_ai.domain.enums import TemplateDocumentType
from legal_ai.domain.template import Template


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.templates = AsyncMock()
    return uow


@pytest.fixture
def service(mock_uow):
    return TemplateService(mock_uow)


class TestCreateTemplate:
    def test_create_template_version_1(self, service, mock_uow):
        mock_uow.templates.get_active_version.return_value = None
        mock_uow.templates.create.side_effect = lambda t: t

        result = asyncio.run(
            service.create_template(
                name="Resolución Test",
                document_type=TemplateDocumentType.RESOLUCION,
                body_template="Body {{employee.first_name}}",
            )
        )
        assert result.version == 1
        assert result.is_active is True
        assert result.name == "Resolución Test"

    def test_create_template_duplicate_raises(self, service, mock_uow):
        existing = Template(
            id=uuid.uuid4(),
            name="Test",
            document_type=TemplateDocumentType.RESOLUCION,
            version=1,
            body_template="body",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_uow.templates.get_active_version.return_value = existing

        with pytest.raises(TemplateNameConflictError):
            asyncio.run(
                service.create_template(
                    name="Test",
                    document_type=TemplateDocumentType.RESOLUCION,
                    body_template="body",
                )
            )


class TestGetTemplate:
    def test_get_template_not_found(self, service, mock_uow):
        mock_uow.templates.get_by_id.return_value = None

        with pytest.raises(TemplateNotFoundError):
            asyncio.run(service.get_template(str(uuid.uuid4())))

    def test_get_template_found(self, service, mock_uow):
        template = Template(
            id=uuid.uuid4(),
            name="Test",
            document_type=TemplateDocumentType.RESOLUCION,
            version=1,
            body_template="body",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_uow.templates.get_by_id.return_value = template

        result = asyncio.run(service.get_template(str(template.id)))
        assert result.id == template.id


class TestUpdateTemplate:
    def test_update_metadata_only_no_new_version(self, service, mock_uow):
        template = Template(
            id=uuid.uuid4(),
            name="Test",
            document_type=TemplateDocumentType.RESOLUCION,
            version=1,
            body_template="body",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_uow.templates.get_by_id.return_value = template
        mock_uow.templates.update.side_effect = lambda t: t

        result = asyncio.run(
            service.update_template(str(template.id), organ_emisor="Nuevo órgano")
        )
        assert result.version == 1
        assert result.organ_emisor == "Nuevo órgano"

    def test_update_content_creates_new_version(self, service, mock_uow):
        template = Template(
            id=uuid.uuid4(),
            name="Test",
            document_type=TemplateDocumentType.RESOLUCION,
            version=1,
            body_template="old body",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_uow.templates.get_by_id.return_value = template
        mock_uow.templates.deactivate_all_versions.return_value = None
        mock_uow.templates.create.side_effect = lambda t: t

        result = asyncio.run(
            service.update_template(str(template.id), body_template="new body")
        )
        assert result.version == 2
        assert result.body_template == "new body"

    def test_update_not_found_raises(self, service, mock_uow):
        mock_uow.templates.get_by_id.return_value = None

        with pytest.raises(TemplateNotFoundError):
            asyncio.run(service.update_template(str(uuid.uuid4()), body_template="x"))


class TestDeactivateTemplate:
    def test_deactivate_template(self, service, mock_uow):
        template = Template(
            id=uuid.uuid4(),
            name="Test",
            document_type=TemplateDocumentType.RESOLUCION,
            version=1,
            body_template="body",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_uow.templates.get_by_id.return_value = template
        mock_uow.templates.update.side_effect = lambda t: t

        result = asyncio.run(service.deactivate_template(str(template.id)))
        assert result.is_active is False

    def test_deactivate_already_inactive_raises(self, service, mock_uow):
        template = Template(
            id=uuid.uuid4(),
            name="Test",
            document_type=TemplateDocumentType.RESOLUCION,
            version=1,
            body_template="body",
            is_active=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_uow.templates.get_by_id.return_value = template

        with pytest.raises(TemplateInactiveError):
            asyncio.run(service.deactivate_template(str(template.id)))

    def test_deactivate_not_found_raises(self, service, mock_uow):
        mock_uow.templates.get_by_id.return_value = None

        with pytest.raises(TemplateNotFoundError):
            asyncio.run(service.deactivate_template(str(uuid.uuid4())))
