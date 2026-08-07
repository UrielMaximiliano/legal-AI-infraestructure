"""Generation-safe corpus reindexing with read-only dry-run by default."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, cast

from legal_ai.adapters.filesystem_corpus import CorpusSourceFile, FilesystemCorpusReader
from legal_ai.application.corpus_ingestion import (
    CorpusIngestionConfiguration,
    CorpusIngestionService,
    _PreparedDocument,
)
from legal_ai.application.embedding_batch import EmbeddingBatchProcessor
from legal_ai.application.legal_chunking import LegalChunkingService
from legal_ai.domain.corpus import CorpusChunk, CorpusDocument
from legal_ai.domain.ingestion import (
    EmbeddingBatch,
    IngestionRun,
    IngestionRunStatus,
    IngestionRunType,
    configuration_hash_for_snapshot,
)
from legal_ai.ports.embedding import EmbeddingProvider, InferenceCoordinationPort
from legal_ai.schemas.corpus_cli import CorpusFailureReport
from legal_ai.schemas.corpus_reindex import CorpusReindexReport, CorpusReindexRequest


class CorpusReindexService:
    def __init__(
        self,
        *,
        uow_factory: Any,
        embedding_provider: EmbeddingProvider | None = None,
        inference_coordinator: InferenceCoordinationPort | None = None,
        chunker: LegalChunkingService | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._provider = embedding_provider
        self._coordinator = inference_coordinator
        self._chunker = chunker or LegalChunkingService()

    async def _select(
        self, request: CorpusReindexRequest
    ) -> tuple[CorpusDocument, ...]:
        async with self._uow_factory() as uow:
            if request.document_ids:
                result: list[CorpusDocument] = []
                for document_id in request.document_ids:
                    document = await uow.corpus_documents.get(document_id)
                    if document is not None:
                        result.append(document)
                return tuple(result)
            # The repository deliberately caps a single page. Walk all pages
            # so a full-corpus reindex cannot silently stop at 1,000 rows.
            page_size = 1000
            selected: list[CorpusDocument] = []
            offset = 0
            while True:
                page = await uow.corpus_documents.list(
                    document_type=request.document_type,
                    document_subtype=request.document_subtype,
                    jurisdiction=request.jurisdiction,
                    review_status=None,
                    limit=page_size,
                    offset=offset,
                )
                selected.extend(
                    document
                    for document in page
                    if (
                        request.language is None
                        or document.language == request.language
                    )
                    and (
                        request.organization is None
                        or document.organization == request.organization
                    )
                )
                if len(page) < page_size:
                    break
                offset += len(page)
            return tuple(selected)

    async def dry_run(self, request: CorpusReindexRequest) -> CorpusReindexReport:
        documents = await self._select(request)
        chunks = sum(
            len(
                self._chunker.chunk(
                    document.normalized_content,
                    document_id=document.id,
                    normalization_version=request.normalization_version,
                    chunking_version=request.chunking_version,
                )
            )
            for document in documents
        )
        return CorpusReindexReport(
            run_id=request.run_id or self._stable_run_id(request, documents),
            mode="dry-run",
            execution_mode="DRY_RUN",
            status="completed",
            documents_selected=len(documents),
            documents_reindexed=0,
            chunks_estimated=chunks,
            batches_estimated=(chunks + request.batch_size - 1) // request.batch_size
            if chunks
            else 0,
            model=request.model,
            dimensions=request.dimensions,
            normalization_version=request.normalization_version,
            chunking_version=request.chunking_version,
        )

    async def execute(self, request: CorpusReindexRequest) -> CorpusReindexReport:
        documents = await self._select(request)
        config = CorpusIngestionConfiguration(
            model=request.model,
            dimensions=request.dimensions,
            normalization_version=request.normalization_version,
            chunking_version=request.chunking_version,
            batch_size=request.batch_size,
        )
        config.validate()
        run_id = request.run_id or self._stable_run_id(request, documents)
        snapshot = asdict(config)
        configuration_hash = configuration_hash_for_snapshot(snapshot)
        staged: list[tuple[_PreparedDocument, int, tuple[uuid.UUID, ...]]] = []
        async with self._uow_factory() as uow:
            run = cast("IngestionRun | None", await uow.ingestion_runs.get(run_id))
            if run is not None:
                if run.configuration_hash != configuration_hash:
                    raise ValueError("INGESTION_CONFIGURATION_HASH_MISMATCH")
                if request.resume and run.status is IngestionRunStatus.INTERRUPTED:
                    run.resume()
                elif run.status is IngestionRunStatus.PENDING:
                    run.start()
                elif run.status is not IngestionRunStatus.RUNNING:
                    raise ValueError("REINDEX_RUN_NOT_RESUMABLE")
                await uow.ingestion_runs.update(run)
            else:
                run = IngestionRun(
                    id=uuid.uuid4(),
                    run_id=run_id,
                    run_type=IngestionRunType.REINDEX,
                    source_identifier="corpus-reindex",
                    configuration_hash=configuration_hash,
                    configuration_snapshot=snapshot,
                    counts={"discovered_count": len(documents)},
                )
                await uow.ingestion_runs.create(run)
                run.start()
                await uow.ingestion_runs.update(run)
            for document in documents:
                generation = (document.active_generation or 0) + 1
                chunks = self._chunker.chunk(
                    document.normalized_content,
                    document_id=document.id,
                    normalization_version=request.normalization_version,
                    chunking_version=request.chunking_version,
                )
                chunk_ids: list[uuid.UUID] = []
                for chunk in chunks:
                    chunk_id = uuid.uuid5(
                        document.id,
                        f"reindex:{generation}:{chunk.chunk_index}:{chunk.content_hash}",
                    )
                    chunk_ids.append(chunk_id)
                    if await uow.corpus_chunks.get(chunk_id) is None:
                        await uow.corpus_chunks.create(
                            CorpusChunk(
                                id=chunk_id,
                                document_id=document.id,
                                content=chunk.content,
                                content_hash=chunk.content_hash,
                                generation=generation,
                                section_index=chunk.section_index,
                                paragraph_index=chunk.paragraph_index,
                                section_type=chunk.section_type.value,
                                article_number=chunk.article_number,
                                token_count=chunk.token_count,
                                chunking_version=chunk.chunking_version,
                                normalization_version=chunk.normalization_version,
                                metadata=chunk.metadata,
                            )
                        )
                existing = await uow.embedding_batches.list_for_run(run.id, generation)
                existing_indices = {batch.batch_index for batch in existing}
                for batch_index, start in enumerate(
                    range(0, len(chunk_ids), request.batch_size)
                ):
                    ids = tuple(chunk_ids[start : start + request.batch_size])
                    if batch_index not in existing_indices:
                        await uow.embedding_batches.create(
                            EmbeddingBatch(
                                id=uuid.uuid5(
                                    run.id, f"reindex:{generation}:{batch_index}"
                                ),
                                ingestion_run_id=run.id,
                                generation=generation,
                                batch_index=batch_index,
                                input_count=len(ids),
                                chunk_ids=ids,
                            )
                        )
                staged.append(
                    (
                        _PreparedDocument(
                            source=CorpusSourceFile(
                                source_identifier=document.source_identifier,
                                extension=".txt",
                                media_type="text/plain",
                                text=document.normalized_content,
                                size_bytes=len(document.normalized_content.encode()),
                            ),
                            document=document,
                            chunks=chunks,
                        ),
                        generation,
                        tuple(chunk_ids),
                    )
                )
        processor = CorpusIngestionService(
            FilesystemCorpusReader(),
            embedding_provider=self._provider,
            inference_coordinator=self._coordinator,
            uow_factory=self._uow_factory,
        )
        provider = self._provider or processor._default_provider(config)
        coordinator = self._coordinator or processor._default_coordinator(config)
        batch_processor = EmbeddingBatchProcessor(
            provider,
            coordinator,
            dimensions=request.dimensions,
            timeout_seconds=30.0,
        )
        failures: list[CorpusFailureReport] = []
        try:
            for batch in await processor._pending_batches(
                run_id, self._uow_factory, staged
            ):
                try:
                    texts = await processor._mark_batch_processing(
                        batch, self._uow_factory
                    )
                    vectors = await batch_processor.embed(texts)
                    await processor._persist_batch_success(
                        batch, vectors, self._uow_factory
                    )
                except Exception as exc:
                    code = getattr(exc, "code", "REINDEX_EMBEDDING_FAILED")
                    await processor._persist_batch_failure(
                        batch, str(code), self._uow_factory
                    )
                    failures.append(
                        CorpusFailureReport(
                            source_identifier="<reindex>",
                            error_code=str(code),
                            stage="EMBEDDING",
                        )
                    )
            result_run = await processor._finalize_execution(
                run_id, staged, bool(failures), failures, self._uow_factory
            )
        finally:
            if self._coordinator is None and hasattr(coordinator, "close"):
                await coordinator.close()
        return CorpusReindexReport(
            run_id=run_id,
            mode="execute",
            execution_mode="EXECUTE",
            status=(
                "completed"
                if result_run.status is IngestionRunStatus.COMPLETED
                else "partial"
            ),
            documents_selected=len(documents),
            documents_reindexed=result_run.processed_documents,
            chunks_estimated=result_run.processed_chunks,
            batches_estimated=(
                (result_run.processed_chunks + request.batch_size - 1)
                // request.batch_size
                if result_run.processed_chunks
                else 0
            ),
            model=request.model,
            dimensions=request.dimensions,
            normalization_version=request.normalization_version,
            chunking_version=request.chunking_version,
            failures=tuple(failure.error_code for failure in failures),
        )

    @staticmethod
    def _stable_run_id(
        request: CorpusReindexRequest, documents: tuple[CorpusDocument, ...]
    ) -> str:
        value = ":".join(str(document.id) for document in documents)
        return f"reindex-{uuid.uuid5(uuid.NAMESPACE_URL, value or 'empty').hex}"
