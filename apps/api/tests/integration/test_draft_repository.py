"""Integration tests for draft persistence and optimistic locking."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.draft_repository import SQLAlchemyDraftRepository
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.template_repository import SQLAlchemyTemplateRepository
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus, TemplateDocumentType
from legal_ai.domain.template import Template
from tests.integration.factories_003 import create_case_file


@pytest.fixture
async def session():
    engine = create_engine()
    async with AsyncSession(engine, expire_on_commit=False) as value:
        yield value
        await value.rollback()
    await engine.dispose()


async def _draft(session: AsyncSession) -> Draft:
    now = datetime.now(UTC)
    case_file_id, _ = await create_case_file(session)
    template = await SQLAlchemyTemplateRepository(session).create(
        Template(
            id=uuid.uuid4(),
            name=f"Template-{uuid.uuid4().hex}",
            document_type=TemplateDocumentType.RESOLUCION,
            version=1,
            body_template="body",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    return Draft(
        id=uuid.uuid4(),
        template_id=template.id,
        case_file_id=case_file_id,
        title="Draft",
        content="content",
        status=DraftStatus.GENERADO,
        version=1,
        generation_number=1,
        context_snapshot={"metadata": {}},
        context_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.integration
async def test_draft_crud_filter_and_optimistic_lock(session) -> None:
    repo = SQLAlchemyDraftRepository(session)
    draft = await repo.create(await _draft(session))
    assert await repo.get_by_id(draft.id) is not None
    listed, total = await repo.list_by_case_file(
        draft.case_file_id, DraftStatus.GENERADO, 0, 10
    )
    assert total == 1 and listed[0].id == draft.id

    draft.content = "changed"
    updated = await repo.update_with_optimistic_lock(draft, 1)
    assert updated is not None and updated.version == 2
    assert await repo.update_with_optimistic_lock(draft, 1) is None


@pytest.mark.integration
async def test_update_status_and_full_update_are_version_guarded(session) -> None:
    repo = SQLAlchemyDraftRepository(session)
    draft = await repo.create(await _draft(session))
    reviewed = await repo.update_status(draft.id, DraftStatus.EN_REVISION, 1)
    assert reviewed is not None and reviewed.version == 2
    assert await repo.update_status(draft.id, DraftStatus.APROBADO, 1) is None

    reviewed.status = DraftStatus.SUPERSEDED
    superseded = await repo.update(reviewed, 2)
    assert superseded is not None and superseded.version == 3
