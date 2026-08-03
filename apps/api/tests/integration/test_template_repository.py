"""Integration tests for document template persistence."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.template_repository import SQLAlchemyTemplateRepository
from legal_ai.domain.enums import TemplateDocumentType
from legal_ai.domain.template import Template


@pytest.fixture
async def session():
    engine = create_engine()
    async with AsyncSession(engine, expire_on_commit=False) as value:
        yield value
        await value.rollback()
    await engine.dispose()


def _template(name: str | None = None, version: int = 1) -> Template:
    now = datetime.now(UTC)
    return Template(
        id=uuid.uuid4(),
        name=name or f"Template-{uuid.uuid4().hex}",
        document_type=TemplateDocumentType.RESOLUCION,
        version=version,
        body_template="{{employee.first_name}}",
        variables=["numero"],
        is_active=True,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.integration
async def test_template_crud_filters_pagination_and_deactivation(session) -> None:
    repo = SQLAlchemyTemplateRepository(session)
    first = await repo.create(_template("Unique searchable template"))
    await repo.create(_template())

    assert await repo.get_by_id(first.id) is not None
    active = await repo.get_active_version(first.name, first.document_type)
    assert active is not None and active.id == first.id
    listed, total = await repo.list_active("resolucion", "searchable", 0, 1)
    assert total == 1 and [item.id for item in listed] == [first.id]

    first.description = "updated"
    assert (await repo.update(first)).description == "updated"
    await repo.deactivate_all_versions(first.name, first.document_type)
    assert await repo.get_active_version(first.name, first.document_type) is None


@pytest.mark.integration
async def test_template_unique_name_type_version_constraint(session) -> None:
    repo = SQLAlchemyTemplateRepository(session)
    name = f"Duplicate-{uuid.uuid4().hex}"
    await repo.create(_template(name))
    with pytest.raises(IntegrityError):
        await repo.create(_template(name))
