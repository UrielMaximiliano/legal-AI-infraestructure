"""Real PostgreSQL evidence for safe, resumable staged-index activation."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.corpus_document_repository import (
    SQLAlchemyCorpusDocumentRepository,
)
from legal_ai.adapters.database.corpus_models import (
    CorpusChunkModel,
    CorpusDocumentModel,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.corpus_activation import CorpusActivationService
from legal_ai.domain.corpus import CorpusIngestionStatus
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from legal_ai.schemas.corpus_activation import CorpusActivationRequest

from .rag_postgres_support import isolated_url, run_alembic

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _seed(*, split: str = "INDEX_90") -> tuple[uuid.UUID, uuid.UUID]:
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    now = datetime.now(UTC)
    external_id = f"ACTIVATION-{uuid.uuid4().hex}"
    engine = create_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(
                CorpusDocumentModel(
                    id=document_id,
                    external_id=external_id,
                    title="Activation fixture",
                    document_type="decreto",
                    document_subtype="designacion_transitoria",
                    jurisdiction="nacion",
                    language="es",
                    organization="test",
                    source_name="isolated-test",
                    source_identifier=f"test://{external_id}",
                    raw_content="Activation fixture raw",
                    raw_content_hash=_hash(external_id + "raw"),
                    normalized_content="Activation fixture normalized",
                    normalized_content_hash=_hash(external_id + "normalized"),
                    metadata_json={"evaluation_split": split},
                    provenance_type="AUTOMATED",
                    review_status="PENDING_REVIEW",
                    review_version=7,
                    ingestion_status=CorpusIngestionStatus.EMBEDDING,
                    embedding_status="PROCESSING",
                    created_by_pipeline_version="006-test",
                    normalization_version="005-test",
                    chunking_version="005-test",
                    active_generation=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                CorpusChunkModel(
                    id=chunk_id,
                    document_id=document_id,
                    generation=1,
                    state="STAGED",
                    section_type="ARTICULO",
                    section_index=0,
                    paragraph_index=0,
                    content="Activation fixture chunk",
                    content_hash=_hash(external_id + "chunk"),
                    token_count=3,
                    embedding=[1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))],
                    embedding_model=EMBEDDING_MODEL,
                    embedding_dimensions=EMBEDDING_DIMENSIONS,
                    normalization_version="005-test",
                    chunking_version="005-test",
                    metadata_json={"evaluation_split": split},
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
    return document_id, chunk_id


async def _cleanup(*document_ids: uuid.UUID) -> None:
    engine = create_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                delete(CorpusDocumentModel).where(
                    CorpusDocumentModel.id.in_(document_ids)
                )
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_activation_is_atomic_idempotent_and_preserves_review() -> None:
    run_alembic("upgrade", "007")
    database = str(isolated_url().database)
    document_id, _ = await _seed()
    request = CorpusActivationRequest(expected_database=database)
    service = CorpusActivationService(uow_factory=UnitOfWork)
    try:
        before = await service.dry_run(request)
        assert before.documents_pending == 1
        assert before.documents_activated == 0

        first = await service.execute(request)
        second = await service.execute(request)
        assert first.documents_activated == 1
        assert second.documents_activated == 0
        assert second.documents_already_active == 1

        engine = create_engine()
        try:
            async with AsyncSession(engine) as session:
                document = await session.get(CorpusDocumentModel, document_id)
                chunks = (
                    await session.execute(
                        select(CorpusChunkModel).where(
                            CorpusChunkModel.document_id == document_id
                        )
                    )
                ).scalars().all()
                assert document is not None
                assert document.active_generation == 1
                assert document.ingestion_status == CorpusIngestionStatus.COMPLETED
                assert document.embedding_status == "EMBEDDED"
                assert document.review_status == "PENDING_REVIEW"
                assert document.review_version == 7
                assert [chunk.state for chunk in chunks] == ["ACTIVE"]
        finally:
            await engine.dispose()
    finally:
        await _cleanup(document_id)


@pytest.mark.asyncio
async def test_activation_rolls_back_document_when_final_update_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_alembic("upgrade", "007")
    database = str(isolated_url().database)
    document_id, _ = await _seed()

    async def fail_update(
        self: SQLAlchemyCorpusDocumentRepository,
        document_ids: tuple[uuid.UUID, ...],
        **kwargs: object,
    ) -> None:
        del self, document_ids, kwargs
        raise RuntimeError("private database detail")

    monkeypatch.setattr(
        SQLAlchemyCorpusDocumentRepository, "update_processing_states", fail_update
    )
    try:
        with pytest.raises(ValueError, match="CORPUS_ACTIVATION_FAILED"):
            await CorpusActivationService(uow_factory=UnitOfWork).execute(
                CorpusActivationRequest(expected_database=database)
            )
        engine = create_engine()
        try:
            async with AsyncSession(engine) as session:
                document = await session.get(CorpusDocumentModel, document_id)
                chunk = (
                    await session.execute(
                        select(CorpusChunkModel).where(
                            CorpusChunkModel.document_id == document_id
                        )
                    )
                ).scalar_one()
                assert document is not None
                assert document.active_generation is None
                assert document.review_version == 7
                assert chunk.state == "STAGED"
        finally:
            await engine.dispose()
    finally:
        await _cleanup(document_id)


@pytest.mark.asyncio
async def test_activation_fails_closed_when_holdout_exists() -> None:
    run_alembic("upgrade", "007")
    database = str(isolated_url().database)
    index_id, _ = await _seed()
    holdout_id, _ = await _seed(split="HOLDOUT_10")
    try:
        with pytest.raises(ValueError, match="CORPUS_ACTIVATION_PREFLIGHT_FAILED"):
            await CorpusActivationService(uow_factory=UnitOfWork).dry_run(
                CorpusActivationRequest(expected_database=database)
            )
    finally:
        await _cleanup(index_id, holdout_id)
