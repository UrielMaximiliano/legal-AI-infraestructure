from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.embeddings.fake_embedding import FakeEmbeddingProvider
from legal_ai.adapters.filesystem_corpus import FilesystemCorpusReader
from legal_ai.application.corpus_ingestion import CorpusIngestionService
from legal_ai.application.inference_coordinator import InferenceCoordinator


async def _cleanup(run_ids: tuple[str, ...], source_identifier: str) -> None:
    engine = create_engine()
    try:
        async with engine.begin() as connection:
            for run_id in run_ids:
                await connection.execute(
                    text(
                        "DELETE FROM ingestion_failures "
                        "WHERE ingestion_run_id IN "
                        "(SELECT id FROM ingestion_runs WHERE run_id = :run_id)"
                    ),
                    {"run_id": run_id},
                )
                await connection.execute(
                    text(
                        "DELETE FROM embedding_batches "
                        "WHERE ingestion_run_id IN "
                        "(SELECT id FROM ingestion_runs WHERE run_id = :run_id)"
                    ),
                    {"run_id": run_id},
                )
                await connection.execute(
                    text("DELETE FROM ingestion_runs WHERE run_id = :run_id"),
                    {"run_id": run_id},
                )
            await connection.execute(
                text("DELETE FROM corpus_documents WHERE source_identifier = :source"),
                {"source": source_identifier},
            )
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_execute_is_atomic_and_idempotent(tmp_path: Path) -> None:
    source_identifier = f"execute-{uuid.uuid4().hex}.txt"
    (tmp_path / source_identifier).write_text(
        "ARTÃCULO 1Â°.- Texto de prueba para ingesta.", encoding="utf-8"
    )
    run_id = f"phase11-{uuid.uuid4().hex}"
    changed_run_id = f"phase11-{uuid.uuid4().hex}"
    service = CorpusIngestionService(
        FilesystemCorpusReader(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
    )
    try:
        first = await service.run(str(tmp_path), execute=True, run_id=run_id)
        assert first.status == "completed"
        assert first.execution_mode == "EXECUTE"
        assert first.dimensions == 2560

        second = await service.run(str(tmp_path), execute=True, run_id=run_id)
        assert second.status == "completed"
        assert second.run_id == run_id

        engine = create_engine()
        try:
            async with engine.connect() as connection:
                counts = await connection.execute(
                    text(
                        "SELECT count(*) AS documents, "
                        "(SELECT count(*) FROM corpus_chunks c "
                        "JOIN corpus_documents d ON d.id = c.document_id "
                        "WHERE d.source_identifier = :source AND c.state = 'ACTIVE') "
                        "AS active_chunks "
                        "FROM corpus_documents WHERE source_identifier = :source"
                    ),
                    {"source": source_identifier},
                )
                row = counts.one()
                assert row.documents == 1
                assert row.active_chunks == 1
        finally:
            await engine.dispose()

        (tmp_path / source_identifier).write_text(
            "ARTÃCULO 1Â°.- Contenido cambiado.", encoding="utf-8"
        )
        changed = await service.run(str(tmp_path), execute=True, run_id=changed_run_id)
        assert changed.status == "completed"
    finally:
        await _cleanup((run_id, changed_run_id), source_identifier)


class _CancelOnceProvider:
    def __init__(self) -> None:
        self.cancel = True
        self.delegate = FakeEmbeddingProvider()

    async def embed_documents(self, texts):
        if self.cancel:
            self.cancel = False
            raise asyncio.CancelledError()
        return await self.delegate.embed_documents(texts)

    async def embed_query(self, text):
        return await self.delegate.embed_query(text)


@pytest.mark.integration
async def test_execute_resume_reuses_staged_batches_after_cancellation(
    tmp_path: Path,
) -> None:
    source_identifier = f"resume-{uuid.uuid4().hex}.txt"
    (tmp_path / source_identifier).write_text(
        "ARTÃCULO 1Â°.- ReanudaciÃ³n controlada.", encoding="utf-8"
    )
    run_id = f"phase11-resume-{uuid.uuid4().hex}"
    provider = _CancelOnceProvider()
    coordinator = InferenceCoordinator(max_queue_size=1)
    service = CorpusIngestionService(
        FilesystemCorpusReader(tmp_path),
        embedding_provider=provider,
        inference_coordinator=coordinator,
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await service.run(str(tmp_path), execute=True, run_id=run_id)
        await coordinator.close()
        resumed = await CorpusIngestionService(
            FilesystemCorpusReader(tmp_path),
            embedding_provider=provider,
        ).run(str(tmp_path), execute=True, run_id=run_id, resume=True)
        assert resumed.status == "completed"
    finally:
        await _cleanup((run_id,), source_identifier)
