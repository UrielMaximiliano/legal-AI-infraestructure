from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.embeddings.fake_embedding import FakeEmbeddingProvider
from legal_ai.adapters.filesystem_corpus import FilesystemCorpusReader
from legal_ai.application.corpus_ingestion import CorpusIngestionService


@pytest.mark.integration
async def test_ingestion_provider_failure_is_partial_and_does_not_publish_chunks(
    tmp_path: Path,
) -> None:
    source = f"failure-{uuid.uuid4().hex}.txt"
    run_id = f"failure-{uuid.uuid4().hex}"
    (tmp_path / source).write_text("ARTICULO 1.- Fallo controlado.", encoding="utf-8")

    class FailingProvider(FakeEmbeddingProvider):
        async def embed_documents(self, texts):
            raise RuntimeError("secret provider details")

    try:
        report = await CorpusIngestionService(
            FilesystemCorpusReader(tmp_path),
            embedding_provider=FailingProvider(),
        ).run(str(tmp_path), execute=True, run_id=run_id)
        assert report.status == "partial"
        assert all(
            "secret" not in failure.model_dump_json() for failure in report.failures
        )
        engine = create_engine()
        try:
            async with engine.connect() as connection:
                active = await connection.execute(
                    text(
                        "SELECT count(*) FROM corpus_chunks c "
                        "JOIN corpus_documents d ON d.id = c.document_id "
                        "WHERE d.source_identifier = :source AND c.state = 'ACTIVE'"
                    ),
                    {"source": source},
                )
                assert active.scalar_one() == 0
        finally:
            await engine.dispose()
    finally:
        engine = create_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM ingestion_failures WHERE ingestion_run_id IN "
                        "(SELECT id FROM ingestion_runs WHERE run_id = :run_id)"
                    ),
                    {"run_id": run_id},
                )
                await connection.execute(
                    text(
                        "DELETE FROM embedding_batches WHERE ingestion_run_id IN "
                        "(SELECT id FROM ingestion_runs WHERE run_id = :run_id)"
                    ),
                    {"run_id": run_id},
                )
                await connection.execute(
                    text("DELETE FROM ingestion_runs WHERE run_id = :run_id"),
                    {"run_id": run_id},
                )
                await connection.execute(
                    text(
                        "DELETE FROM corpus_documents WHERE source_identifier = :source"
                    ),
                    {"source": source},
                )
        finally:
            await engine.dispose()
