"""Integration tests for designation persistence."""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.designation_repository import (
    SQLAlchemyDesignationRepository,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.domain.designation_data import DesignationData
from tests.integration.factories_003 import create_case_file


@pytest.fixture
async def session():
    engine = create_engine()
    async with AsyncSession(engine, expire_on_commit=False) as value:
        yield value
        await value.rollback()
    await engine.dispose()


def _designation(case_file_id: uuid.UUID) -> DesignationData:
    now = datetime.now(UTC)
    return DesignationData(
        id=uuid.uuid4(),
        case_file_id=case_file_id,
        position_name="Asesor",
        start_date=date.today(),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.integration
async def test_designation_create_get_and_update(session) -> None:
    case_file_id, _ = await create_case_file(session)
    repo = SQLAlchemyDesignationRepository(session)
    designation = await repo.create(_designation(case_file_id))
    assert (await repo.get_by_case_file_id(case_file_id)).id == designation.id
    designation.position_name = "Director"
    assert (await repo.update(designation)).position_name == "Director"


@pytest.mark.integration
async def test_one_designation_per_case_file(session) -> None:
    case_file_id, _ = await create_case_file(session)
    repo = SQLAlchemyDesignationRepository(session)
    await repo.create(_designation(case_file_id))
    with pytest.raises(IntegrityError):
        await repo.create(_designation(case_file_id))
