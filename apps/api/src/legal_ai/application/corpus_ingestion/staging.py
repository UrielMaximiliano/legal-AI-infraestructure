"""Persistencia staged del run: documentos, chunks y batches de embedding.

Toda escritura de staging ocurre dentro de una única transacción corta que
abre el llamador; aquí no se abren ni cierran UoWs salvo en los helpers que
reciben ``uow_factory`` explícito (reanudación).
"""

from __future__ import annotations

import uuid
from typing import Any

from legal_ai.adapters.filesystem_corpus import (
    CorpusReaderError,
    CorpusSourceFile,
)
from legal_ai.application.corpus_ingestion.configuration import (
    CorpusIngestionConfiguration,
)
from legal_ai.application.corpus_ingestion.preparation import (
    DocumentPreparer,
    PreparedDocument,
    error_code,
)
from legal_ai.application.corpus_ingestion.reports import execution_report
from legal_ai.domain.corpus import CorpusChunk, CorpusDocument
from legal_ai.domain.ingestion import (
    EmbeddingBatch,
    IngestionFailure,
    IngestionRun,
    IngestionRunStatus,
    IngestionRunType,
)
from legal_ai.schemas.corpus_cli import CorpusDryRunReport, CorpusFailureReport

StagedDocument = tuple[PreparedDocument, int, tuple[uuid.UUID, ...]]


async def prepare_documents(
    reader: Any,
    preparer: DocumentPreparer,
    identifiers: tuple[str, ...],
    config: CorpusIngestionConfiguration,
    *,
    fail_fast: bool,
) -> tuple[list[PreparedDocument], list[CorpusFailureReport]]:
    """Lee y prepara los agregados completos fuera de transacciones."""

    from legal_ai.application.corpus_normalization import CorpusNormalizationError
    from legal_ai.application.legal_chunking import LegalChunkingError

    prepared: list[PreparedDocument] = []
    failures: list[CorpusFailureReport] = []
    for identifier in identifiers:
        try:
            source = await reader.read_document(identifier)
            prepared.append(preparer.prepare(source, config))
        except (
            CorpusReaderError,
            CorpusNormalizationError,
            LegalChunkingError,
            ValueError,
        ) as exc:
            failures.append(
                CorpusFailureReport(
                    source_identifier=identifier,
                    error_code=error_code(exc, "CORPUS_INGESTION_VALIDATION_FAILED"),
                    stage="VALIDATION",
                )
            )
            if fail_fast:
                break
    return prepared, failures


async def open_or_resume_run(
    uow: Any,
    *,
    effective_run_id: str,
    config: CorpusIngestionConfiguration,
    snapshot: dict[str, Any],
    configuration_hash: str,
    identifiers: tuple[str, ...],
    prepared: list[PreparedDocument],
    failures: list[CorpusFailureReport],
    resume: bool,
) -> tuple[IngestionRun, CorpusDryRunReport | None]:
    """Crea o reanuda el run y registra las fallas de descubrimiento.

    Devuelve ``(run, None)`` o ``(run, report)`` cuando el run ya estaba
    completado y no se pidió reanudación; en ese caso el reporte existente es
    la respuesta final y la transacción confirma sin re-procesar.
    """

    run = await uow.ingestion_runs.get(effective_run_id)
    created_run = False
    if run is not None:
        if run.configuration_hash != configuration_hash:
            raise ValueError("INGESTION_CONFIGURATION_HASH_MISMATCH")
        if not resume and run.status is IngestionRunStatus.COMPLETED:
            return (
                run,
                execution_report(effective_run_id, identifiers, failures, run, config),
            )
        if resume and run.status is IngestionRunStatus.INTERRUPTED:
            run.resume()
        elif run.status is IngestionRunStatus.PENDING:
            run.start()
        elif run.status is not IngestionRunStatus.RUNNING:
            raise ValueError("INGESTION_RUN_NOT_RESUMABLE")
        await uow.ingestion_runs.update(run)
    else:
        created_run = True
        run = IngestionRun(
            id=uuid.uuid4(),
            run_id=effective_run_id,
            run_type=IngestionRunType.INGEST,
            source_identifier=config.source_name,
            configuration_hash=configuration_hash,
            configuration_snapshot=snapshot,
            counts={
                "discovered_count": len(identifiers),
                "parsed_count": len(prepared),
                "normalized_count": len(prepared),
                "validated_count": len(prepared),
                "chunked_count": sum(len(item.chunks) for item in prepared),
                "failed_count": len(failures),
            },
        )
        await uow.ingestion_runs.create(run)
        run.start()
        await uow.ingestion_runs.update(run)

    if created_run:
        for failure in failures:
            await uow.ingestion_failures.create(
                IngestionFailure(
                    id=uuid.uuid4(),
                    ingestion_run_id=run.id,
                    stage=failure.stage,
                    error_code=failure.error_code,
                    message=failure.error_code,
                    source_identifier=failure.source_identifier,
                )
            )
    run.counts.update(
        {
            "discovered_count": len(identifiers),
            "parsed_count": len(prepared),
            "normalized_count": len(prepared),
            "validated_count": len(prepared),
            "chunked_count": sum(len(item.chunks) for item in prepared),
            "failed_count": len(failures),
        }
    )
    await uow.ingestion_runs.update(run)
    return run, None


async def stage_documents(
    uow: Any,
    run: IngestionRun,
    prepared: list[PreparedDocument],
    config: CorpusIngestionConfiguration,
) -> list[StagedDocument]:
    """Upsert de documentos, chunks determinísticos y batches pendientes."""

    staged: list[StagedDocument] = []
    for item in prepared:
        result = await uow.corpus_documents.upsert(item.document)
        document = result.document
        if result.status == "UNCHANGED" and document.active_generation is not None:
            continue
        generation = (document.active_generation or 0) + 1
        existing_chunks = await uow.corpus_chunks.list_generation(
            document.id, generation
        )
        chunk_ids: list[uuid.UUID] = []
        for index, legal_chunk in enumerate(item.chunks):
            chunk_id = uuid.uuid5(
                document.id,
                f"005:{generation}:{index}:{legal_chunk.content_hash}",
            )
            chunk_ids.append(chunk_id)
            if any(existing.id == chunk_id for existing in existing_chunks):
                continue
            await uow.corpus_chunks.create(
                CorpusChunk(
                    id=chunk_id,
                    document_id=document.id,
                    content=legal_chunk.content,
                    content_hash=legal_chunk.content_hash,
                    generation=generation,
                    section_index=legal_chunk.section_index,
                    paragraph_index=legal_chunk.paragraph_index,
                    section_type=legal_chunk.section_type.value,
                    article_number=legal_chunk.article_number,
                    token_count=legal_chunk.token_count,
                    chunking_version=legal_chunk.chunking_version,
                    normalization_version=legal_chunk.normalization_version,
                    metadata=legal_chunk.metadata,
                )
            )
        existing_batches = await uow.embedding_batches.list_for_run(run.id, generation)
        existing_by_index = {batch.batch_index: batch for batch in existing_batches}
        for batch_index, start in enumerate(
            range(0, len(chunk_ids), config.batch_size)
        ):
            ids = tuple(chunk_ids[start : start + config.batch_size])
            if batch_index not in existing_by_index:
                await uow.embedding_batches.create(
                    EmbeddingBatch(
                        id=uuid.uuid5(run.id, f"005:{generation}:{batch_index}"),
                        ingestion_run_id=run.id,
                        generation=generation,
                        batch_index=batch_index,
                        input_count=len(ids),
                        chunk_ids=ids,
                    )
                )
        staged.append((item, generation, tuple(chunk_ids)))
    return staged


async def resume_staged(run_id: str, uow_factory: Any) -> list[StagedDocument]:
    """Reconstruye las generaciones staged de un run interrumpido."""

    async with uow_factory() as uow:
        run = await uow.ingestion_runs.get(run_id)
        if run is None:
            raise ValueError("INGESTION_RUN_NOT_FOUND")
        batches = await uow.embedding_batches.list_all_for_run(run.id)
        grouped: dict[tuple[uuid.UUID, int], list[uuid.UUID]] = {}
        documents: dict[tuple[uuid.UUID, int], CorpusDocument] = {}
        for batch in batches:
            if not batch.chunk_ids:
                continue
            first_chunk = await uow.corpus_chunks.get(batch.chunk_ids[0])
            if first_chunk is None:
                continue
            key = (first_chunk.document_id, batch.generation)
            grouped.setdefault(key, []).extend(batch.chunk_ids)
            document = await uow.corpus_documents.get(first_chunk.document_id)
            if document is not None:
                documents[key] = document
        result: list[StagedDocument] = []
        for (document_id, generation), ids in grouped.items():
            document = documents.get((document_id, generation))
            if document is None:
                continue
            result.append(
                (
                    PreparedDocument(
                        source=CorpusSourceFile(
                            source_identifier=document.source_identifier,
                            extension=".txt",
                            media_type="text/plain",
                            text="",
                            size_bytes=0,
                        ),
                        document=document,
                        chunks=(),
                    ),
                    generation,
                    tuple(dict.fromkeys(ids)),
                )
            )
        return result
