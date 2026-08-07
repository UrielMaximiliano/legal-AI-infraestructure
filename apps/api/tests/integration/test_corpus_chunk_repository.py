from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.corpus_chunk_repository import (
    SQLAlchemyCorpusChunkRepository,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.corpus import CorpusChunk, CorpusDocument, sha256_text
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


def test_chunk_repository_is_explicitly_named() -> None:
    assert SQLAlchemyCorpusChunkRepository.__name__


@pytest.mark.integration
async def test_staged_generation_can_be_swapped_atomically() -> None:
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    raw = "raw chunk fixture"
    normalized = "normalized chunk fixture"
    document = CorpusDocument(
        id=document_id,
        source_identifier=f"fixture/{document_id}.txt",
        raw_content=raw,
        normalized_content=normalized,
        raw_content_hash=sha256_text(raw),
        normalized_content_hash=sha256_text(normalized),
        external_id=f"chunk-{document_id}",
        source_name="fixture",
        metadata={"pipeline_version": "005"},
    )
    chunk = CorpusChunk(
        id=chunk_id,
        document_id=document_id,
        content="Artículo 1°.- fixture",
        content_hash=sha256_text("Artículo 1°.- fixture"),
        generation=1,
        section_index=0,
        paragraph_index=0,
        embedding=tuple([0.0] * EMBEDDING_DIMENSIONS),
        embedding_model=EMBEDDING_MODEL,
        embedding_dimensions=EMBEDDING_DIMENSIONS,
    )
    try:
        async with UnitOfWork() as uow:
            await uow.corpus_documents.create(document)
            await uow.corpus_chunks.create(chunk)
            assert await uow.corpus_chunks.get(chunk_id) is not None
            await uow.corpus_chunks.upsert(chunk)
            await uow.corpus_chunks.activate_generation(document_id, 1)
            await uow.corpus_documents.swap_generation(document_id, 1)
        async with UnitOfWork() as uow:
            active = await uow.corpus_chunks.list_active(document_id, 1)
            assert len(active) == 1
            await uow.rollback()
        with pytest.raises(ValueError, match="CORPUS_GENERATION_NOT_FOUND"):
            async with UnitOfWork() as uow:
                await uow.corpus_chunks.activate_generation(document_id, 2)
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
