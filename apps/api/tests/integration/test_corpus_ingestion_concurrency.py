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


@pytest.mark.integration
async def test_same_run_id_concurrent_ingestion_is_idempotent(tmp_path: Path) -> None:
    source = f"concurrent-{uuid.uuid4().hex}.txt"
    run_id = f"concurrent-{uuid.uuid4().hex}"
    (tmp_path / source).write_text("ARTICULO 1.- Concurrencia.", encoding="utf-8")
    try:
        services = [
            CorpusIngestionService(
                FilesystemCorpusReader(tmp_path),
                embedding_provider=FakeEmbeddingProvider(),
            )
            for _ in range(2)
        ]
        results = await asyncio.gather(
            *(
                service.run(str(tmp_path), execute=True, run_id=run_id)
                for service in services
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, Exception) is False for result in results) >= 1
        engine = create_engine()
        try:
            async with engine.connect() as connection:
                result = await connection.execute(
                    text(
                        "SELECT count(*) FROM corpus_documents "
                        "WHERE source_identifier = :source"
                    ),
                    {"source": source},
                )
                assert result.scalar_one() == 1
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
