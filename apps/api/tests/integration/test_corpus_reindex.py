from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.embeddings.fake_embedding import FakeEmbeddingProvider
from legal_ai.adapters.filesystem_corpus import FilesystemCorpusReader
from legal_ai.application.corpus_ingestion import CorpusIngestionService
from legal_ai.application.corpus_reindex import CorpusReindexService
from legal_ai.schemas.corpus_reindex import CorpusReindexRequest


@pytest.mark.integration
async def test_reindex_dry_run_has_no_writes_and_execute_swaps_generation(
    tmp_path: Path,
) -> None:
    source = f"reindex-{uuid.uuid4().hex}.txt"
    (tmp_path / source).write_text(
        "ARTÃCULO 1Â°.- Documento para reindexaciÃ³n.", encoding="utf-8"
    )
    run_id = f"reindex-{uuid.uuid4().hex}"
    ingest = CorpusIngestionService(
        FilesystemCorpusReader(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
    )
    try:
        await ingest.run(str(tmp_path), execute=True, run_id=f"seed-{run_id}")
        async with UnitOfWork() as uow:
            documents = await uow.corpus_documents.list(
                document_type="decreto",
                document_subtype="designacion_transitoria",
                jurisdiction="nacion",
            )
            document = next(
                item for item in documents if item.source_identifier == source
            )
        request = CorpusReindexRequest(document_ids=(document.id,), run_id=run_id)
        service = CorpusReindexService(
            uow_factory=UnitOfWork,
            embedding_provider=FakeEmbeddingProvider(),
        )
        before = await _counts(document.id)
        report = await service.dry_run(request)
        after = await _counts(document.id)
        assert report.execution_mode == "DRY_RUN"
        assert before == after
        executed = await service.execute(request)
        assert executed.status == "completed"
        assert executed.documents_reindexed == 1
        async with UnitOfWork() as uow:
            updated = await uow.corpus_documents.get(document.id)
            assert updated is not None
            assert updated.active_generation == 2
    finally:
        engine = create_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM embedding_batches WHERE ingestion_run_id IN "
                        "(SELECT id FROM ingestion_runs WHERE run_id LIKE :prefix)"
                    ),
                    {"prefix": f"%{run_id}"},
                )
                await connection.execute(
                    text("DELETE FROM ingestion_runs WHERE run_id LIKE :prefix"),
                    {"prefix": f"%{run_id}"},
                )
                await connection.execute(
                    text(
                        "DELETE FROM corpus_documents WHERE source_identifier = :source"
                    ),
                    {"source": source},
                )
        finally:
            await engine.dispose()


async def _counts(document_id: uuid.UUID) -> tuple[int, int, int]:
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM corpus_chunks WHERE document_id=:id), "
                    "(SELECT count(*) FROM ingestion_runs WHERE run_type='REINDEX'), "
                    "(SELECT count(*) FROM embedding_batches)"
                ),
                {"id": document_id},
            )
            row = result.one()
            return int(row[0]), int(row[1]), int(row[2])
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_reindex_failure_preserves_active_generation(tmp_path: Path) -> None:
    source = f"reindex-failure-{uuid.uuid4().hex}.txt"
    (tmp_path / source).write_text("ARTICULO 1.- Reindex failure.", encoding="utf-8")
    seed_run = f"reindex-failure-seed-{uuid.uuid4().hex}"
    failed_run = f"reindex-failure-run-{uuid.uuid4().hex}"
    await CorpusIngestionService(
        FilesystemCorpusReader(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
    ).run(str(tmp_path), execute=True, run_id=seed_run)
    try:
        async with UnitOfWork() as uow:
            document = next(
                item
                for item in await uow.corpus_documents.list(
                    document_type="decreto",
                    document_subtype="designacion_transitoria",
                    jurisdiction="nacion",
                )
                if item.source_identifier == source
            )

        class FailingProvider(FakeEmbeddingProvider):
            async def embed_documents(self, texts):
                raise RuntimeError("reindex provider failure")

        report = await CorpusReindexService(
            uow_factory=UnitOfWork,
            embedding_provider=FailingProvider(),
        ).execute(CorpusReindexRequest(document_ids=(document.id,), run_id=failed_run))
        assert report.status == "partial"
        async with UnitOfWork() as uow:
            current = await uow.corpus_documents.get(document.id)
            assert current is not None
            assert current.active_generation == 1
    finally:
        engine = create_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM embedding_batches WHERE ingestion_run_id IN "
                        "(SELECT id FROM ingestion_runs "
                        "WHERE run_id IN (:seed, :failed))"
                    ),
                    {"seed": seed_run, "failed": failed_run},
                )
                await connection.execute(
                    text("DELETE FROM ingestion_runs WHERE run_id IN (:seed, :failed)"),
                    {"seed": seed_run, "failed": failed_run},
                )
                await connection.execute(
                    text(
                        "DELETE FROM corpus_documents WHERE source_identifier = :source"
                    ),
                    {"source": source},
                )
        finally:
            await engine.dispose()
