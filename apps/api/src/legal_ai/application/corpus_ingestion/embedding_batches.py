"""Ciclo de vida de batches de embedding dentro del run de ingesta.

Cada helper abre su propia transacción corta vía ``uow_factory``; las llamadas
al proveedor ocurren siempre fuera de ellas.
"""

from __future__ import annotations

import uuid
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime
from typing import Any

from legal_ai.application.corpus_ingestion.configuration import (
    CorpusIngestionConfiguration,
)
from legal_ai.application.corpus_ingestion.staging import StagedDocument
from legal_ai.domain.corpus import CorpusIngestionStatus
from legal_ai.domain.ingestion import (
    EmbeddingBatch,
    EmbeddingBatchStatus,
    IngestionFailure,
    IngestionRunStatus,
)


def default_provider(config: CorpusIngestionConfiguration) -> Any:
    """Proveedor por defecto cuando no se inyecta ninguno.

    La ejecución es deliberadamente offline-safe sin inyección; la
    composición de producción inyecta el adaptador Ollama explícitamente.
    """

    from legal_ai.adapters.embeddings.fake_embedding import FakeEmbeddingProvider

    return FakeEmbeddingProvider(dimensions=config.dimensions)


def default_coordinator() -> Any:
    from legal_ai.application.inference_coordinator import InferenceCoordinator

    return InferenceCoordinator(max_queue_size=1, wait_timeout=30.0)


async def pending_batches(
    run_id: str,
    uow_factory: Any,
    staged: list[StagedDocument],
) -> tuple[EmbeddingBatch, ...]:
    async with uow_factory() as uow:
        run = await uow.ingestion_runs.get(run_id)
        if run is None:
            raise ValueError("INGESTION_RUN_NOT_FOUND")
        all_batches: list[EmbeddingBatch] = []
        if staged:
            for _, generation, _ in staged:
                all_batches.extend(
                    await uow.embedding_batches.list_for_run(run.id, generation)
                )
        else:
            all_batches.extend(await uow.embedding_batches.list_all_for_run(run.id))
        return tuple(
            batch
            for batch in sorted(
                all_batches, key=lambda item: (item.generation, item.batch_index)
            )
            if batch.status
            in {
                EmbeddingBatchStatus.PENDING,
                EmbeddingBatchStatus.FAILED_RETRYABLE,
                EmbeddingBatchStatus.PROCESSING,
            }
        )


async def mark_batch_processing(
    batch: EmbeddingBatch, uow_factory: Any
) -> tuple[str, ...]:
    """Marca el batch en PROCESSING y devuelve los textos a embeber."""

    async with uow_factory() as uow:
        current = await uow.embedding_batches.get(batch.id)
        if current is None:
            raise ValueError("EMBEDDING_BATCH_NOT_FOUND")
        if current.status is EmbeddingBatchStatus.PROCESSING:
            current.transition(EmbeddingBatchStatus.FAILED_RETRYABLE)
        if current.status is not EmbeddingBatchStatus.PROCESSING:
            current.transition(EmbeddingBatchStatus.PROCESSING)
        current.attempt_count += 1
        current.started_at = datetime.now(UTC)
        current.error_code = None
        await uow.embedding_batches.update(current)
        texts: list[str] = []
        document_id: uuid.UUID | None = None
        for chunk_id in current.chunk_ids:
            chunk = await uow.corpus_chunks.get(chunk_id)
            if chunk is None:
                raise ValueError("CORPUS_CHUNK_NOT_FOUND")
            document_id = chunk.document_id
            texts.append(chunk.content)
        if document_id is None:
            raise ValueError("EMBEDDING_BATCH_EMPTY")
        await uow.corpus_documents.update_processing_state(
            document_id,
            ingestion_status=CorpusIngestionStatus.EMBEDDING.value,
            embedding_status="PROCESSING",
        )
        return tuple(texts)


async def persist_batch_success(
    batch: EmbeddingBatch,
    vectors: list[list[float]],
    uow_factory: Any,
) -> None:
    async with uow_factory() as uow:
        current = await uow.embedding_batches.get(batch.id)
        if current is None:
            raise ValueError("EMBEDDING_BATCH_NOT_FOUND")
        if current.status is not EmbeddingBatchStatus.PROCESSING:
            raise ValueError("EMBEDDING_BATCH_STATUS_INVALID")
        for chunk_id, vector in zip(current.chunk_ids, vectors, strict=True):
            chunk = await uow.corpus_chunks.get(chunk_id)
            if chunk is None:
                raise ValueError("CORPUS_CHUNK_NOT_FOUND")
            await uow.corpus_chunks.update(
                dataclass_replace(
                    chunk,
                    embedding=tuple(vector),
                    embedding_model=current.embedding_model,
                    embedding_dimensions=current.embedding_dimensions,
                    state="STAGED",
                )
            )
        current.transition(EmbeddingBatchStatus.SUCCEEDED)
        current.finished_at = datetime.now(UTC)
        await uow.embedding_batches.update(current)


async def persist_batch_failure(
    batch: EmbeddingBatch,
    error_code_value: str,
    uow_factory: Any,
) -> None:
    async with uow_factory() as uow:
        current = await uow.embedding_batches.get(batch.id)
        if current is None:
            return
        if current.status is EmbeddingBatchStatus.PROCESSING:
            current.transition(EmbeddingBatchStatus.FAILED_RETRYABLE)
        current.error_code = error_code_value
        current.finished_at = datetime.now(UTC)
        await uow.embedding_batches.update(current)
        await uow.ingestion_failures.create(
            IngestionFailure(
                id=uuid.uuid4(),
                ingestion_run_id=current.ingestion_run_id,
                stage="EMBEDDING",
                error_code=error_code_value,
                message=error_code_value,
                retryable=True,
                batch_id=current.id,
            )
        )


async def interrupt_run(run_id: str, uow_factory: Any) -> None:
    """Marca el run como INTERRUPTED si sigue RUNNING (p. ej. cancelación)."""

    async with uow_factory() as uow:
        run = await uow.ingestion_runs.get(run_id)
        if run is not None and run.status is IngestionRunStatus.RUNNING:
            run.finish(
                IngestionRunStatus.INTERRUPTED,
                error_code="INGESTION_INTERRUPTED",
            )
            await uow.ingestion_runs.update(run)
