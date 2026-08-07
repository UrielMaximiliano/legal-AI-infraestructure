from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.corpus_document_repository import (
    SQLAlchemyCorpusDeduplicationLookup,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.filesystem_corpus import FilesystemCorpusReader
from legal_ai.application.corpus_ingestion import CorpusIngestionService
from legal_ai.application.corpus_normalization import CorpusNormalizationService
from legal_ai.domain.corpus import CorpusDocument, sha256_text

TABLES = (
    "corpus_documents",
    "corpus_chunks",
    "ingestion_runs",
    "ingestion_failures",
    "embedding_batches",
)


async def _counts(session: AsyncSession) -> dict[str, int]:
    values: dict[str, int] = {}
    for table in TABLES:
        result = await session.execute(text(f"SELECT count(*) FROM {table}"))
        values[table] = int(result.scalar_one())
    return values


@pytest.mark.integration
async def test_dry_run_postgresql_snapshot_has_zero_writes(tmp_path: Path) -> None:
    (tmp_path / "document.txt").write_text(
        "ARTÃCULO 1Â°.- DesignaciÃ³n transitoria.", encoding="utf-8"
    )
    engine = create_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            before = await _counts(session)
            report = await CorpusIngestionService(
                FilesystemCorpusReader(tmp_path),
                deduplication_lookup=SQLAlchemyCorpusDeduplicationLookup(session),
            ).dry_run(str(tmp_path))
            await session.rollback()
            after = await _counts(session)
            assert report.execution_mode == "DRY_RUN"
            assert before == after
            assert "raw_content" not in report.model_dump_json()
            assert str(tmp_path) not in report.model_dump_json()
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_dry_run_classifies_persisted_identity_and_hash(tmp_path: Path) -> None:
    content = "ARTÃCULO 1Â°.- Persistido"
    external_id = "persisted-dry-run"
    (tmp_path / "document.json").write_text(
        '{"external_id":"persisted-dry-run","content":"ARTÃCULO 1Â°.- Persistido"}',
        encoding="utf-8",
    )
    normalized = CorpusNormalizationService().normalize(content)
    document = CorpusDocument(
        id=uuid.uuid4(),
        source_identifier="fixture/persisted-dry-run.txt",
        raw_content=content,
        normalized_content=normalized.normalized_content,
        raw_content_hash=sha256_text(content),
        normalized_content_hash=normalized.normalized_content_hash,
        external_id=external_id,
        source_name="filesystem",
        metadata={"pipeline_version": "005"},
    )
    try:
        async with UnitOfWork() as uow:
            await uow.corpus_documents.create(document)
        engine = create_engine()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                report = await CorpusIngestionService(
                    FilesystemCorpusReader(tmp_path),
                    deduplication_lookup=SQLAlchemyCorpusDeduplicationLookup(session),
                ).dry_run(str(tmp_path))
                await session.rollback()
                assert report.deduplication["SAME_ID_SAME_CONTENT"] == 1
                assert report.documents_new_estimate == 0
        finally:
            await engine.dispose()
    finally:
        cleanup_engine = create_engine()
        try:
            async with cleanup_engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM corpus_documents WHERE id = :id"),
                    {"id": document.id},
                )
        finally:
            await cleanup_engine.dispose()
