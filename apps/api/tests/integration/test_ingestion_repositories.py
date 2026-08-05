from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.ingestion_repository import (
    SQLAlchemyEmbeddingBatchRepository,
    SQLAlchemyIngestionFailureRepository,
    SQLAlchemyIngestionRunRepository,
)
from legal_ai.adapters.database.semantic_search_models import SemanticSearchRunModel
from legal_ai.adapters.database.semantic_search_run_repository import (
    SQLAlchemySemanticSearchRunRepository,
)
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.corpus import CorpusDocument, sha256_text
from legal_ai.domain.ingestion import (
    EmbeddingBatch,
    EmbeddingBatchStatus,
    IngestionFailure,
    IngestionRun,
    IngestionRunType,
    configuration_hash_for_snapshot,
)
from legal_ai.domain.semantic_search import SemanticSearchRun, SemanticSearchStatus


def test_ingestion_repository_adapters_exist() -> None:
    assert SQLAlchemyIngestionRunRepository.__name__
    assert SQLAlchemyIngestionFailureRepository.__name__
    assert SQLAlchemyEmbeddingBatchRepository.__name__
    assert SQLAlchemySemanticSearchRunRepository.__name__


@pytest.mark.integration
async def test_runs_failures_and_batches_round_trip() -> None:
    run = IngestionRun(
        uuid.uuid4(),
        f"repo-run-{uuid.uuid4().hex}",
        IngestionRunType.INGEST,
        source_identifier="fixture/corpus",
        configuration_snapshot={"model": "qwen3-embedding:0.6b", "dimensions": 1024},
        configuration_hash=configuration_hash_for_snapshot(
            {"model": "qwen3-embedding:0.6b", "dimensions": 1024}
        ),
        counts={
            "discovered_count": 1,
            "parsed_count": 2,
            "normalized_count": 3,
            "validated_count": 4,
            "chunked_count": 5,
            "embedded_count": 6,
            "indexed_count": 7,
            "failed_count": 8,
        },
    )
    document = CorpusDocument(
        id=uuid.uuid4(),
        source_identifier="fixture/corpus/document.txt",
        raw_content="raw repository document",
        normalized_content="normalized repository document",
        raw_content_hash=sha256_text("raw repository document"),
        normalized_content_hash=sha256_text("normalized repository document"),
        external_id=f"repo-doc-{uuid.uuid4().hex}",
        source_name="fixture",
        metadata={"pipeline_version": "005"},
    )
    failure = IngestionFailure(
        id=uuid.uuid4(),
        ingestion_run_id=run.id,
        stage="PARSE",
        error_code="CORPUS_PARSE_FAILED",
        message="sanitized",
        source_identifier="fixture/corpus/document.txt",
        document_id=document.id,
        batch_id=None,
    )
    batch = EmbeddingBatch(
        id=uuid.uuid4(),
        ingestion_run_id=run.id,
        generation=1,
        batch_index=0,
        input_count=1,
        chunk_ids=(uuid.uuid4(),),
    )
    failure_without_refs = IngestionFailure(
        id=uuid.uuid4(),
        ingestion_run_id=run.id,
        stage="NORMALIZE",
        error_code="CORPUS_NORMALIZATION_FAILED",
        message="sanitized without references",
    )
    engine = create_engine()
    try:
        async with UnitOfWork() as uow:
            await uow.ingestion_runs.create(run)
            await uow.corpus_documents.create(document)
            batch_id = batch.id
            await uow.embedding_batches.create(batch)
            failure = IngestionFailure(
                id=failure.id,
                ingestion_run_id=run.id,
                stage=failure.stage,
                error_code=failure.error_code,
                message=failure.message,
                source_identifier=failure.source_identifier,
                document_id=document.id,
                batch_id=batch_id,
            )
            await uow.ingestion_failures.create(
                IngestionFailure(
                    id=failure.id,
                    ingestion_run_id=failure.ingestion_run_id,
                    stage=failure.stage,
                    error_code=failure.error_code,
                    message=failure.message,
                    source_identifier=failure.source_identifier,
                    document_id=document.id,
                    batch_id=batch_id,
                )
            )
            await uow.ingestion_failures.create(failure_without_refs)
        async with UnitOfWork() as uow:
            loaded = await uow.ingestion_runs.get(run.run_id)
            loaded_failure = await uow.ingestion_failures.get(failure.id)
            loaded_failure_without_refs = await uow.ingestion_failures.get(
                failure_without_refs.id
            )
            assert loaded_failure is not None
            assert loaded_failure.source_identifier == failure.source_identifier
            assert loaded_failure.document_id == document.id
            assert loaded_failure.batch_id == batch.id
            assert loaded_failure_without_refs is not None
            assert loaded_failure_without_refs.source_identifier is None
            assert loaded_failure_without_refs.document_id is None
            assert loaded_failure_without_refs.batch_id is None
            loaded_batch = await uow.embedding_batches.get(batch.id)
            assert loaded is not None
            assert loaded.source_identifier == run.source_identifier
            assert loaded.configuration_hash == run.configuration_hash
            assert loaded.configuration_snapshot == run.configuration_snapshot
            assert loaded.counts == run.counts
            assert loaded_batch is not None
            assert loaded_batch.generation == batch.generation
            assert loaded_batch.batch_index == batch.batch_index
            assert loaded_batch.input_count == batch.input_count
            assert loaded_batch.chunk_ids == batch.chunk_ids
            assert loaded_batch.embedding_model == batch.embedding_model
            assert loaded_batch.embedding_dimensions == batch.embedding_dimensions
            assert loaded_batch.attempt_count == batch.attempt_count
            batch.transition(EmbeddingBatchStatus.PROCESSING)
            await uow.embedding_batches.update(batch)
            await uow.rollback()
    finally:
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM ingestion_runs WHERE id = :id"), {"id": run.id}
                )
                await connection.execute(
                    text("DELETE FROM corpus_documents WHERE id = :id"),
                    {"id": document.id},
                )
        finally:
            await engine.dispose()


@pytest.mark.integration
async def test_minimized_search_audit_round_trip() -> None:
    run_id = uuid.uuid4()
    audit = SemanticSearchRun(
        id=run_id,
        query_hash="a" * 64,
        filters_sanitized={
            "document_type": "decreto",
            "document_subtype": "designacion_transitoria",
            "jurisdiction": "nacion",
            "review_status": "REVIEWED",
        },
        top_k=3,
        minimum_score=None,
        embedding_model="qwen3-embedding:0.6b",
        embedding_dimensions=1024,
        result_count=1,
        duration_ms=12,
        status=SemanticSearchStatus.SUCCEEDED,
        request_id=f"integration-{run_id.hex}",
    )
    engine = create_engine()
    try:
        async with UnitOfWork() as uow:
            await uow.semantic_search_runs.create(audit)
        async with UnitOfWork() as uow:
            assert uow._session is not None
            row = await uow._session.get(SemanticSearchRunModel, run_id)
            assert row is not None
            assert row.query_hash == "a" * 64
            assert row.request_id == audit.request_id
            await uow.rollback()
    finally:
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM semantic_search_runs WHERE id = :id"),
                    {"id": run_id},
                )
        finally:
            await engine.dispose()
