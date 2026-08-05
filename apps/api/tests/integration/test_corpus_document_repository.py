"""PostgreSQL coverage for document identity and review CAS."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.corpus_document_repository import (
    SQLAlchemyCorpusDocumentRepository,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.corpus import (
    CorpusChunk,
    CorpusDocument,
    CorpusDocumentNotFoundError,
    InvalidReviewTransitionError,
    ReviewStatus,
    ReviewVersionMismatchError,
    sha256_text,
)


def test_document_repository_is_explicitly_named() -> None:
    assert SQLAlchemyCorpusDocumentRepository.__name__


@pytest.mark.integration
async def test_upsert_and_review_cas_have_one_winner() -> None:
    document_id = uuid.uuid4()
    raw = "raw integration fixture"
    normalized = "normalized integration fixture"
    document = CorpusDocument(
        id=document_id,
        source_identifier=f"fixture/{document_id}.txt",
        raw_content=raw,
        normalized_content=normalized,
        raw_content_hash=sha256_text(raw),
        normalized_content_hash=sha256_text(normalized),
        external_id=f"integration-{document_id}",
        source_name="fixture",
        metadata={"pipeline_version": "005"},
    )
    try:
        async with UnitOfWork() as uow:
            created = await uow.corpus_documents.upsert(document)
            assert created.status == "CREATED"
            updated = await uow.corpus_documents.upsert(document)
            assert updated.status == "UNCHANGED"
            assert updated.document.review_version == 1
            assert await uow.corpus_documents.get(uuid.uuid4()) is None
            with pytest.raises(ValueError, match="CORPUS_PAGINATION_INVALID"):
                await uow.corpus_documents.list(limit=0)
            reviewed = await uow.corpus_documents.compare_and_swap_review(
                document_id,
                expected_version=1,
                expected_status=ReviewStatus.PENDING_REVIEW,
                new_status=ReviewStatus.REVIEWED,
                reviewed_by="integration",
            )
            assert reviewed.review_version == 2
            with pytest.raises(InvalidReviewTransitionError):
                await uow.corpus_documents.compare_and_swap_review(
                    document_id,
                    expected_version=2,
                    expected_status=ReviewStatus.REVIEWED,
                    new_status=ReviewStatus.REJECTED,
                    reviewed_by="invalid-transition",
                    reason="terminal",
                )
            with pytest.raises(CorpusDocumentNotFoundError):
                await uow.corpus_documents.compare_and_swap_review(
                    uuid.uuid4(),
                    expected_version=1,
                    expected_status=ReviewStatus.PENDING_REVIEW,
                    new_status=ReviewStatus.REVIEWED,
                    reviewed_by="missing",
                )
        with pytest.raises(ReviewVersionMismatchError):
            async with UnitOfWork() as uow:
                await uow.corpus_documents.compare_and_swap_review(
                    document_id,
                    expected_version=1,
                    expected_status=ReviewStatus.PENDING_REVIEW,
                    new_status=ReviewStatus.REJECTED,
                    reviewed_by="loser",
                    reason="stale",
                )
    finally:
        engine = create_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM corpus_documents WHERE id = :id"),
                    {"id": document_id},
                )
        finally:
            await engine.dispose()


@pytest.mark.integration
async def test_concurrent_identical_upserts_have_one_creator() -> None:
    document_id = uuid.uuid4()
    raw = "concurrent raw fixture"
    normalized = "concurrent normalized fixture"

    def make_document() -> CorpusDocument:
        return CorpusDocument(
            id=document_id,
            source_identifier=f"fixture/{document_id}.txt",
            raw_content=raw,
            normalized_content=normalized,
            raw_content_hash=sha256_text(raw),
            normalized_content_hash=sha256_text(normalized),
            external_id=f"concurrent-{document_id}",
            source_name="fixture-concurrent",
            metadata={"pipeline_version": "005"},
        )

    async def insert_one() -> str:
        async with UnitOfWork() as uow:
            outcome = await uow.corpus_documents.upsert(make_document())
            return outcome.status

    try:
        statuses = await asyncio.gather(insert_one(), insert_one())
        assert sorted(statuses) == ["CREATED", "UNCHANGED"]
        existing_statuses = await asyncio.gather(insert_one(), insert_one())
        assert existing_statuses == ["UNCHANGED", "UNCHANGED"]
        async with UnitOfWork() as uow:
            loaded = await uow.corpus_documents.get(document_id)
            assert loaded is not None
            assert loaded.review_version == 1
            assert loaded.active_generation is None
            await uow.rollback()
    finally:
        engine = create_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM corpus_documents WHERE id = :id"),
                    {"id": document_id},
                )
        finally:
            await engine.dispose()


@pytest.mark.integration
async def test_upsert_rejects_missing_external_id_without_fallback() -> None:
    raw = "external id required"
    document = CorpusDocument(
        id=uuid.uuid4(),
        source_identifier="fixture/missing-external.txt",
        raw_content=raw,
        normalized_content=raw,
        raw_content_hash=sha256_text(raw),
        normalized_content_hash=sha256_text(raw),
        external_id="   ",
        source_name="fixture",
    )
    with pytest.raises(ValueError, match="INVALID_CORPUS_EXTERNAL_ID"):
        async with UnitOfWork() as uow:
            await uow.corpus_documents.upsert(document)
            await uow.rollback()


@pytest.mark.integration
async def test_upsert_changed_content_preserves_active_generation() -> None:
    document_id = uuid.uuid4()
    first_raw = "first raw content"
    first_normalized = "first normalized content"
    second_raw = "second raw content"
    second_normalized = "second normalized content"

    def make_document(raw: str, normalized: str) -> CorpusDocument:
        return CorpusDocument(
            id=document_id,
            source_identifier=f"fixture/{document_id}.txt",
            raw_content=raw,
            normalized_content=normalized,
            raw_content_hash=sha256_text(raw),
            normalized_content_hash=sha256_text(normalized),
            external_id=f"updated-{document_id}",
            source_name="fixture-updated",
            metadata={"pipeline_version": "005"},
        )

    try:
        async with UnitOfWork() as uow:
            await uow.corpus_documents.upsert(
                make_document(first_raw, first_normalized)
            )
            await uow.corpus_chunks.create(
                CorpusChunk(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    content="Artículo 1°.- staging",
                    content_hash=sha256_text("Artículo 1°.- staging"),
                    generation=7,
                    section_index=0,
                    paragraph_index=0,
                    embedding=tuple([0.0] * 1024),
                    embedding_model="qwen3-embedding:0.6b",
                    embedding_dimensions=1024,
                )
            )
            await uow.corpus_chunks.activate_generation(document_id, 7)
            await uow.corpus_documents.swap_generation(document_id, 7)
            outcome = await uow.corpus_documents.upsert(
                make_document(second_raw, second_normalized)
            )
            assert outcome.status == "UPDATED"
            assert outcome.document.active_generation == 7
            assert outcome.document.raw_content_hash == sha256_text(second_raw)
            assert "review_status" in outcome.changed_fields
            assert "review_version" in outcome.changed_fields
    finally:
        engine = create_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM corpus_documents WHERE id = :id"),
                    {"id": document_id},
                )
        finally:
            await engine.dispose()
