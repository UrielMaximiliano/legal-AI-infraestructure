"""Activación de generaciones y finalización del run de ingesta."""

from __future__ import annotations

from typing import Any, cast

from legal_ai.application.corpus_ingestion.staging import StagedDocument
from legal_ai.domain.corpus import CorpusIngestionStatus
from legal_ai.domain.ingestion import (
    EmbeddingBatchStatus,
    IngestionRun,
    IngestionRunStatus,
)
from legal_ai.schemas.corpus_cli import CorpusFailureReport


async def finalize_execution(
    run_id: str,
    staged: list[StagedDocument],
    has_failures: bool,
    failures: list[CorpusFailureReport],
    uow_factory: Any,
) -> IngestionRun:
    """Activa las generaciones completas y cierra el run (COMPLETED/PARTIAL)."""

    async with uow_factory() as uow:
        run = cast("IngestionRun | None", await uow.ingestion_runs.get(run_id))
        if run is None:
            raise ValueError("INGESTION_RUN_NOT_FOUND")
        completed_documents = 0
        completed_chunks = 0
        for item, generation, chunk_ids in staged:
            batches = await uow.embedding_batches.list_for_run(run.id, generation)
            complete = bool(batches) and all(
                batch.status is EmbeddingBatchStatus.SUCCEEDED for batch in batches
            )
            if complete and len(chunk_ids) == sum(
                batch.input_count for batch in batches
            ):
                await uow.corpus_chunks.activate_generation(
                    item.document.id, generation
                )
                await uow.corpus_documents.swap_generation(item.document.id, generation)
                await uow.corpus_documents.update_processing_state(
                    item.document.id,
                    ingestion_status=CorpusIngestionStatus.COMPLETED.value,
                    embedding_status="EMBEDDED",
                )
                completed_documents += 1
                completed_chunks += len(chunk_ids)
            else:
                await uow.corpus_documents.update_processing_state(
                    item.document.id,
                    ingestion_status=CorpusIngestionStatus.FAILED.value,
                    embedding_status="FAILED",
                )
        run.processed_documents = completed_documents
        run.processed_chunks = completed_chunks
        run.counts.update(
            {
                "embedded_count": completed_chunks,
                "indexed_count": completed_chunks,
                "failed_count": len(failures),
            }
        )
        if has_failures:
            run.finish(IngestionRunStatus.PARTIAL, error_code=None)
        else:
            run.finish(IngestionRunStatus.COMPLETED)
        await uow.ingestion_runs.update(run)
        return run
