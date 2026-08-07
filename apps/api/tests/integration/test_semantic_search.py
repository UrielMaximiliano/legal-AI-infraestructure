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
from legal_ai.application.corpus_review import CorpusReviewService
from legal_ai.application.semantic_search import SemanticSearchService
from legal_ai.schemas.corpus_review import CorpusReviewRequest
from legal_ai.schemas.semantic_search import SemanticSearchRequest


@pytest.mark.integration
async def test_semantic_search_uses_reviewed_active_generation_and_audits(
    tmp_path: Path,
) -> None:
    source = f"search-{uuid.uuid4().hex}.txt"
    (tmp_path / source).write_text(
        "ARTÃCULO 1Â°.- DesignaciÃ³n transitoria de prueba.", encoding="utf-8"
    )
    run_id = f"search-seed-{uuid.uuid4().hex}"
    provider = FakeEmbeddingProvider()
    document_id: uuid.UUID | None = None
    try:
        report = await CorpusIngestionService(
            FilesystemCorpusReader(tmp_path), embedding_provider=provider
        ).run(str(tmp_path), execute=True, run_id=run_id)
        assert report.status == "completed"
        async with UnitOfWork() as uow:
            documents = await uow.corpus_documents.list(
                document_type="decreto",
                document_subtype="designacion_transitoria",
                jurisdiction="nacion",
            )
            document = next(
                item for item in documents if item.source_identifier == source
            )
            document_id = document.id
        async with UnitOfWork() as uow:
            await CorpusReviewService(uow).review(
                CorpusReviewRequest(
                    document_id=document.id,
                    approve=True,
                    reviewed_by="search-reviewer",
                    expected_version=1,
                ),
                request_id="search-review-request",
            )
        service = SemanticSearchService(
            uow_factory=UnitOfWork,
            embedding_provider=FakeEmbeddingProvider(),
        )
        response = await service.search(
            SemanticSearchRequest(
                query="designaciÃ³n transitoria",
                document_type="decreto",
                document_subtype="designacion_transitoria",
                jurisdiction="nacion",
                top_k=3,
            ),
            request_id="search-request",
        )
        assert response.result_count == 1
        assert response.results[0].document_id == str(document.id)
        assert "raw_content" not in response.model_dump_json()
        engine = create_engine()
        try:
            async with engine.connect() as connection:
                audit = await connection.execute(
                    text(
                        "SELECT count(*) FROM semantic_search_runs "
                        "WHERE request_id = 'search-request'"
                    )
                )
                assert audit.scalar_one() == 1
        finally:
            await engine.dispose()
    finally:
        engine = create_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM review_events WHERE resource_type = "
                        "'CORPUS_DOCUMENT' AND resource_id = :resource"
                    ),
                    {"resource": str(document_id) if document_id else ""},
                )
                await connection.execute(
                    text(
                        "DELETE FROM semantic_search_runs "
                        "WHERE request_id = 'search-request'"
                    )
                )
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
