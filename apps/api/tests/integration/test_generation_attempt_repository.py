"""Integration tests for generation attempt persistence and idempotency."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.generation_attempt_repository import (
    SQLAlchemyGenerationAttemptRepository,
)
from legal_ai.adapters.database.template_repository import SQLAlchemyTemplateRepository
from legal_ai.domain.enums import GenerationStatus, TemplateDocumentType
from legal_ai.domain.generation_attempt import GenerationAttempt
from legal_ai.domain.template import Template
from tests.integration.factories_003 import create_case_file


@pytest.fixture
async def session():
    engine = create_engine()
    async with AsyncSession(engine, expire_on_commit=False) as value:
        yield value
        await value.rollback()
    await engine.dispose()


async def _attempt(session: AsyncSession, key: str | None) -> GenerationAttempt:
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
    return GenerationAttempt(
        id=uuid.uuid4(),
        case_file_id=case_file_id,
        template_id=template.id,
        idempotency_key=key,
        model="test",
        prompt_hash="a" * 64,
        prompt_content="private prompt",
        status=GenerationStatus.IN_PROGRESS,
        started_at=now,
        created_at=now,
    )


@pytest.mark.integration
async def test_attempt_crud_list_update_and_delete(session) -> None:
    repo = SQLAlchemyGenerationAttemptRepository(session)
    attempt = await repo.create(await _attempt(session, f"key-{uuid.uuid4()}"))
    assert (await repo.get_by_idempotency_key(attempt.idempotency_key)).id == attempt.id
    assert (await repo.get_by_id(attempt.id)).id == attempt.id
    assert [item.id for item in await repo.list_by_case_file(attempt.case_file_id)] == [
        attempt.id
    ]
    attempt.status = GenerationStatus.COMPLETED
    assert (await repo.update(attempt)).status == GenerationStatus.COMPLETED
    await repo.delete_by_idempotency_key(attempt.idempotency_key)
    assert await repo.get_by_idempotency_key(attempt.idempotency_key) is None


@pytest.mark.integration
async def test_idempotency_unique_and_cleanup_window(session) -> None:
    repo = SQLAlchemyGenerationAttemptRepository(session)
    key = f"key-{uuid.uuid4()}"
    await repo.create(await _attempt(session, key))
    duplicate = await _attempt(session, key)
    with pytest.raises(IntegrityError):
        await repo.create(duplicate)
    await session.rollback()

    expired = await _attempt(session, None)
    expired.created_at = datetime.now(UTC) - timedelta(hours=25)
    await repo.create(expired)
    assert await repo.cleanup_expired(24) >= 1
