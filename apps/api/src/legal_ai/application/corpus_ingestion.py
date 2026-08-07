"""Application orchestration for safe corpus discovery and dry-run ingestion."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from math import ceil
from pathlib import PurePosixPath
from typing import Any, Literal, cast

from legal_ai.adapters.filesystem_corpus import (
    CorpusReaderError,
    CorpusSourceFile,
    FilesystemCorpusReader,
)
from legal_ai.application.corpus_metadata import CorpusMetadataService
from legal_ai.application.corpus_normalization import (
    CorpusNormalizationError,
    CorpusNormalizationService,
)
from legal_ai.application.embedding_batch import EmbeddingBatchProcessor
from legal_ai.application.legal_chunking import (
    LegalChunk,
    LegalChunkingError,
    LegalChunkingService,
)
from legal_ai.domain.corpus import (
    CorpusChunk,
    CorpusDeduplicationRecord,
    CorpusDocument,
    CorpusIngestionStatus,
)
from legal_ai.domain.ingestion import (
    EmbeddingBatch,
    EmbeddingBatchStatus,
    IngestionFailure,
    IngestionRun,
    IngestionRunStatus,
    IngestionRunType,
    configuration_hash_for_snapshot,
)
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from legal_ai.ports.corpus_repositories import CorpusDeduplicationLookupPort
from legal_ai.ports.embedding import (
    EmbeddingProvider,
    InferenceCoordinationPort,
)
from legal_ai.schemas.corpus_cli import CorpusDryRunReport, CorpusFailureReport


@dataclass(frozen=True, slots=True)
class CorpusIngestionConfiguration:
    model: str = EMBEDDING_MODEL
    dimensions: int = EMBEDDING_DIMENSIONS
    source_name: str = "filesystem"
    document_type: str = "decreto"
    document_subtype: str = "designacion_transitoria"
    jurisdiction: str = "nacion"
    language: str = "es"
    normalization_version: str = "005-nfc-v1"
    chunking_version: str = "005-legal-v1"
    batch_size: int = 16
    max_chunks: int = 100_000

    def validate(self) -> None:
        if self.model != EMBEDDING_MODEL or self.dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError("EMBEDDING_CONTRACT_INVALID")
        if not self.source_name.strip():
            raise ValueError("CORPUS_SOURCE_NAME_INVALID")
        if (
            not self.document_type.strip()
            or not self.document_subtype.strip()
            or not self.jurisdiction.strip()
            or not self.language.strip()
            or not self.normalization_version.strip()
            or not self.chunking_version.strip()
            or self.batch_size <= 0
            or self.batch_size > 256
            or self.max_chunks <= 0
        ):
            raise ValueError("CORPUS_CONFIGURATION_INVALID")


@dataclass(frozen=True, slots=True)
class _PreparedDocument:
    source: CorpusSourceFile
    document: CorpusDocument
    chunks: tuple[LegalChunk, ...]


def _error_code(exc: BaseException, default: str) -> str:
    value = getattr(exc, "code", None)
    if isinstance(value, str) and value and value.replace("_", "").isalnum():
        return value[:80]
    return default


class CorpusIngestionService:
    """Keep heavy parsing outside DB transactions; dry-run opens no UoW."""

    def __init__(
        self,
        reader: FilesystemCorpusReader,
        *,
        normalizer: CorpusNormalizationService | None = None,
        metadata_service: CorpusMetadataService | None = None,
        chunker: LegalChunkingService | None = None,
        deduplication_lookup: CorpusDeduplicationLookupPort | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        inference_coordinator: InferenceCoordinationPort | None = None,
        uow_factory: Any | None = None,
    ) -> None:
        self.reader = reader
        self.normalizer = normalizer or CorpusNormalizationService()
        self.metadata_service = metadata_service or CorpusMetadataService()
        self.chunker = chunker or LegalChunkingService()
        self.deduplication_lookup = deduplication_lookup
        self.embedding_provider = embedding_provider
        self.inference_coordinator = inference_coordinator
        self._uow_factory = uow_factory

    async def dry_run(
        self,
        root: str,
        *,
        configuration: CorpusIngestionConfiguration | None = None,
        limit: int | None = None,
        fail_fast: bool = False,
    ) -> CorpusDryRunReport:
        config = configuration or CorpusIngestionConfiguration()
        config.validate()
        discovery = await self.reader.discover_report(root, fail_fast=fail_fast)
        identifiers = discovery.files
        if limit is not None:
            if limit <= 0:
                raise ValueError("CORPUS_LIMIT_INVALID")
            identifiers = identifiers[:limit]
        report = await self._process(
            identifiers,
            config=config,
            execute=False,
            fail_fast=fail_fast,
            discovery_failures=discovery.failures,
        )
        return report

    async def run(
        self,
        root: str,
        *,
        configuration: CorpusIngestionConfiguration | None = None,
        execute: bool = False,
        limit: int | None = None,
        fail_fast: bool = False,
        run_id: str | None = None,
        resume: bool = False,
    ) -> CorpusDryRunReport:
        """Run the pipeline.  Without execute this is strictly dry-run."""

        if execute:
            return await self._execute(
                root,
                configuration=configuration,
                limit=limit,
                fail_fast=fail_fast,
                run_id=run_id,
                resume=resume,
            )
        config = configuration or CorpusIngestionConfiguration()
        config.validate()
        discovery = await self.reader.discover_report(root, fail_fast=fail_fast)
        identifiers = discovery.files
        if limit is not None:
            if limit <= 0:
                raise ValueError("CORPUS_LIMIT_INVALID")
            identifiers = identifiers[:limit]
        if not execute:
            return await self._process(
                identifiers,
                config=config,
                execute=False,
                fail_fast=fail_fast,
                discovery_failures=discovery.failures,
            )

        raise AssertionError("unreachable")

    async def _execute(
        self,
        root: str,
        *,
        configuration: CorpusIngestionConfiguration | None,
        limit: int | None,
        fail_fast: bool,
        run_id: str | None,
        resume: bool,
    ) -> CorpusDryRunReport:
        """Execute ingestion with short DB transactions around inference."""
        config = configuration or CorpusIngestionConfiguration()
        config.validate()
        if run_id is not None and (not run_id.strip() or len(run_id) > 128):
            raise ValueError("INGESTION_RUN_ID_INVALID")
        if resume and run_id is None:
            raise ValueError("CORPUS_RESUME_REQUIRES_RUN_ID")
        effective_run_id = run_id or f"ingest-{uuid.uuid4().hex}"
        discovery = await self.reader.discover_report(root, fail_fast=fail_fast)
        identifiers = discovery.files
        if limit is not None:
            if limit <= 0:
                raise ValueError("CORPUS_LIMIT_INVALID")
            identifiers = identifiers[:limit]
        failures: list[CorpusFailureReport] = [
            CorpusFailureReport(
                source_identifier=getattr(
                    item, "source_identifier", "<invalid-source>"
                ),
                error_code=getattr(item, "error_code", "CORPUS_DISCOVERY_FAILED"),
                stage=getattr(item, "stage", "DISCOVERY"),
                message=getattr(item, "message", None),
            )
            for item in discovery.failures
        ]
        prepared: list[_PreparedDocument] = []
        for identifier in identifiers:
            try:
                source = await self.reader.read_document(identifier)
                prepared.append(self._prepare_document(source, config))
            except (
                CorpusReaderError,
                CorpusNormalizationError,
                LegalChunkingError,
                ValueError,
            ) as exc:
                failures.append(
                    CorpusFailureReport(
                        source_identifier=identifier,
                        error_code=_error_code(
                            exc, "CORPUS_INGESTION_VALIDATION_FAILED"
                        ),
                        stage="VALIDATION",
                    )
                )
                if fail_fast:
                    break

        snapshot = asdict(config)
        configuration_hash = configuration_hash_for_snapshot(snapshot)
        if self._uow_factory is None:
            from legal_ai.adapters.database.unit_of_work import UnitOfWork

            uow_factory: Any = UnitOfWork
        else:
            uow_factory = self._uow_factory
        run: IngestionRun | None
        created_run = False
        staged: list[tuple[_PreparedDocument, int, tuple[uuid.UUID, ...]]] = []
        try:
            async with uow_factory() as uow:
                run = cast(
                    "IngestionRun | None",
                    await uow.ingestion_runs.get(effective_run_id),
                )
                if run is not None:
                    if run.configuration_hash != configuration_hash:
                        raise ValueError("INGESTION_CONFIGURATION_HASH_MISMATCH")
                    if not resume and run.status is IngestionRunStatus.COMPLETED:
                        return self._execution_report(
                            effective_run_id,
                            identifiers,
                            failures,
                            run,
                            config,
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

                if run is None:  # pragma: no cover - branches create or load it
                    raise RuntimeError("INGESTION_RUN_NOT_INITIALIZED")
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
                for item in prepared:
                    result = await uow.corpus_documents.upsert(item.document)
                    document = result.document
                    if (
                        result.status == "UNCHANGED"
                        and document.active_generation is not None
                    ):
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
                    existing_batches = await uow.embedding_batches.list_for_run(
                        run.id, generation
                    )
                    existing_by_index = {
                        batch.batch_index: batch for batch in existing_batches
                    }
                    for batch_index, start in enumerate(
                        range(0, len(chunk_ids), config.batch_size)
                    ):
                        ids = tuple(chunk_ids[start : start + config.batch_size])
                        if batch_index not in existing_by_index:
                            await uow.embedding_batches.create(
                                EmbeddingBatch(
                                    id=uuid.uuid5(
                                        run.id, f"005:{generation}:{batch_index}"
                                    ),
                                    ingestion_run_id=run.id,
                                    generation=generation,
                                    batch_index=batch_index,
                                    input_count=len(ids),
                                    chunk_ids=ids,
                                )
                            )
                    staged.append((item, generation, tuple(chunk_ids)))
                run.counts["failed_count"] = len(failures)
                await uow.ingestion_runs.update(run)
        except Exception:
            raise

        if resume and not staged:
            staged = await self._resume_staged(effective_run_id, uow_factory)

        provider = self.embedding_provider or self._default_provider(config)
        coordinator = self.inference_coordinator or self._default_coordinator(config)
        try:
            batches = await self._pending_batches(effective_run_id, uow_factory, staged)
            failed = False
            batch_processor = EmbeddingBatchProcessor(
                provider,
                coordinator,
                dimensions=config.dimensions,
                timeout_seconds=30.0,
            )
            for batch in batches:
                try:
                    texts = await self._mark_batch_processing(batch, uow_factory)
                    vectors = await batch_processor.embed(texts)
                    await self._persist_batch_success(batch, vectors, uow_factory)
                except asyncio.CancelledError:
                    await self._interrupt_run(effective_run_id, uow_factory)
                    raise
                except Exception as exc:  # provider and batch errors are sanitized
                    failed = True
                    error_code = _error_code(exc, "EMBEDDING_BATCH_FAILED")
                    await self._persist_batch_failure(batch, error_code, uow_factory)
                    failures.append(
                        CorpusFailureReport(
                            source_identifier="<embedding>",
                            error_code=error_code,
                            stage="EMBEDDING",
                        )
                    )
                    if fail_fast:
                        break

            run = await self._finalize_execution(
                effective_run_id,
                staged,
                failed or bool(failures),
                failures,
                uow_factory,
            )
        finally:
            if self.inference_coordinator is None and hasattr(coordinator, "close"):
                await coordinator.close()
        return self._execution_report(
            effective_run_id,
            identifiers,
            failures,
            run,
            config,
        )

    def _prepare_document(
        self, source: CorpusSourceFile, config: CorpusIngestionConfiguration
    ) -> _PreparedDocument:
        """Build the complete domain aggregate before opening a transaction."""
        normalized = self.normalizer.normalize(
            source.text,
            config=replace(
                self.normalizer.config,
                version=config.normalization_version,
            ),
        )
        values: dict[str, object] = dict(source.metadata or {})
        values.update(
            {
                "external_id": values.get(
                    "external_id", PurePosixPath(source.source_identifier).stem
                ),
                "source_name": values.get("source_name", config.source_name),
                "source_identifier": values.get(
                    "source_identifier", source.source_identifier
                ),
                "document_type": values.get("document_type", config.document_type),
                "document_subtype": values.get(
                    "document_subtype", config.document_subtype
                ),
                "jurisdiction": values.get("jurisdiction", config.jurisdiction),
                "language": values.get("language", config.language),
                "normalization_version": config.normalization_version,
                "chunking_version": config.chunking_version,
                "pipeline_version": "005",
            }
        )
        metadata = self.metadata_service.validate(values)
        document_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"005:{metadata.source_name}:{metadata.external_id}",
        )
        chunks = self.chunker.chunk(
            normalized.normalized_content,
            document_id=document_id,
            chunking_version=config.chunking_version,
            normalization_version=config.normalization_version,
        )
        title_value = values.get("title")
        document = CorpusDocument(
            id=document_id,
            source_identifier=metadata.source_identifier,
            raw_content=normalized.raw_content,
            normalized_content=normalized.normalized_content,
            raw_content_hash=normalized.raw_content_hash,
            normalized_content_hash=normalized.normalized_content_hash,
            external_id=metadata.external_id,
            source_name=metadata.source_name,
            title=title_value if isinstance(title_value, str) else None,
            document_type=metadata.document_type,
            document_subtype=metadata.document_subtype,
            jurisdiction=metadata.jurisdiction,
            language=metadata.language,
            organization=metadata.organization,
            source_url=metadata.source_url,
            publication_date=metadata.publication_date,
            metadata=metadata.sanitized_dict(),
            normalization_version=config.normalization_version,
            chunking_version=config.chunking_version,
        )
        return _PreparedDocument(source=source, document=document, chunks=chunks)

    @staticmethod
    def _default_provider(config: CorpusIngestionConfiguration) -> EmbeddingProvider:
        # Execution is deliberately offline-safe when no provider is injected.
        # Production composition injects the Ollama adapter explicitly.
        from legal_ai.adapters.embeddings.fake_embedding import FakeEmbeddingProvider

        return FakeEmbeddingProvider(dimensions=config.dimensions)

    @staticmethod
    def _default_coordinator(
        config: CorpusIngestionConfiguration,
    ) -> InferenceCoordinationPort:
        del config
        from legal_ai.application.inference_coordinator import InferenceCoordinator

        return InferenceCoordinator(max_queue_size=1, wait_timeout=30.0)

    async def _pending_batches(
        self,
        run_id: str,
        uow_factory: Any,
        staged: list[tuple[_PreparedDocument, int, tuple[uuid.UUID, ...]]],
    ) -> tuple[EmbeddingBatch, ...]:
        async with uow_factory() as uow:
            run = cast("IngestionRun | None", await uow.ingestion_runs.get(run_id))
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

    async def _resume_staged(
        self, run_id: str, uow_factory: Any
    ) -> list[tuple[_PreparedDocument, int, tuple[uuid.UUID, ...]]]:
        """Reconstruct staged generations for an interrupted run."""
        async with uow_factory() as uow:
            run = cast("IngestionRun | None", await uow.ingestion_runs.get(run_id))
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
            result: list[tuple[_PreparedDocument, int, tuple[uuid.UUID, ...]]] = []
            for (document_id, generation), ids in grouped.items():
                document = documents.get((document_id, generation))
                if document is None:
                    continue
                result.append(
                    (
                        _PreparedDocument(
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

    async def _mark_batch_processing(
        self, batch: EmbeddingBatch, uow_factory: Any
    ) -> tuple[str, ...]:
        async with uow_factory() as uow:
            current = cast(
                "EmbeddingBatch | None", await uow.embedding_batches.get(batch.id)
            )
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

    async def _persist_batch_success(
        self,
        batch: EmbeddingBatch,
        vectors: list[list[float]],
        uow_factory: Any,
    ) -> None:
        async with uow_factory() as uow:
            current = cast(
                "EmbeddingBatch | None", await uow.embedding_batches.get(batch.id)
            )
            if current is None:
                raise ValueError("EMBEDDING_BATCH_NOT_FOUND")
            if current.status is not EmbeddingBatchStatus.PROCESSING:
                raise ValueError("EMBEDDING_BATCH_STATUS_INVALID")
            for chunk_id, vector in zip(current.chunk_ids, vectors, strict=True):
                chunk = await uow.corpus_chunks.get(chunk_id)
                if chunk is None:
                    raise ValueError("CORPUS_CHUNK_NOT_FOUND")
                await uow.corpus_chunks.update(
                    replace(
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

    async def _persist_batch_failure(
        self,
        batch: EmbeddingBatch,
        error_code: str,
        uow_factory: Any,
    ) -> None:
        async with uow_factory() as uow:
            current = cast(
                "EmbeddingBatch | None", await uow.embedding_batches.get(batch.id)
            )
            if current is None:
                return
            if current.status is EmbeddingBatchStatus.PROCESSING:
                current.transition(EmbeddingBatchStatus.FAILED_RETRYABLE)
            current.error_code = error_code
            current.finished_at = datetime.now(UTC)
            await uow.embedding_batches.update(current)
            await uow.ingestion_failures.create(
                IngestionFailure(
                    id=uuid.uuid4(),
                    ingestion_run_id=current.ingestion_run_id,
                    stage="EMBEDDING",
                    error_code=error_code,
                    message=error_code,
                    retryable=True,
                    batch_id=current.id,
                )
            )

    async def _interrupt_run(self, run_id: str, uow_factory: Any) -> None:
        async with uow_factory() as uow:
            run = cast("IngestionRun | None", await uow.ingestion_runs.get(run_id))
            if run is not None and run.status is IngestionRunStatus.RUNNING:
                run.finish(
                    IngestionRunStatus.INTERRUPTED,
                    error_code="INGESTION_INTERRUPTED",
                )
                await uow.ingestion_runs.update(run)

    async def _finalize_execution(
        self,
        run_id: str,
        staged: list[tuple[_PreparedDocument, int, tuple[uuid.UUID, ...]]],
        has_failures: bool,
        failures: list[CorpusFailureReport],
        uow_factory: Any,
    ) -> IngestionRun:
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
                    await uow.corpus_documents.swap_generation(
                        item.document.id, generation
                    )
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
                run.finish(
                    IngestionRunStatus.PARTIAL,
                    error_code=None,
                )
            else:
                run.finish(IngestionRunStatus.COMPLETED)
            await uow.ingestion_runs.update(run)
            return run

    def _execution_report(
        self,
        run_id: str,
        identifiers: tuple[str, ...],
        failures: list[CorpusFailureReport],
        run: IngestionRun,
        config: CorpusIngestionConfiguration | None = None,
    ) -> CorpusDryRunReport:
        config = config or CorpusIngestionConfiguration()
        return CorpusDryRunReport(
            run_id=run_id,
            request_id=run_id,
            mode="execute",
            execution_mode="EXECUTE",
            status=(
                "completed" if run.status is IngestionRunStatus.COMPLETED else "partial"
            ),
            files_discovered=len(identifiers),
            files_valid=max(0, len(identifiers) - len(failures)),
            files_invalid=len(failures),
            documents_new_estimate=run.processed_documents,
            documents_duplicate_estimate=0,
            chunks_estimated=run.processed_chunks,
            normalization_version=config.normalization_version,
            chunking_version=config.chunking_version,
            model=config.model,
            dimensions=config.dimensions,
            failures=failures,
            batch_size=config.batch_size,
            estimated_batch_count=(
                (run.processed_chunks + config.batch_size - 1) // config.batch_size
                if run.processed_chunks
                else 0
            ),
            max_chunks=config.max_chunks,
        )

    async def _process(
        self,
        identifiers: tuple[str, ...],
        *,
        config: CorpusIngestionConfiguration,
        execute: bool,
        fail_fast: bool,
        discovery_failures: tuple[object, ...] = (),
    ) -> CorpusDryRunReport:
        failures: list[CorpusFailureReport] = [
            CorpusFailureReport(
                source_identifier=getattr(
                    item, "source_identifier", "<invalid-source>"
                ),
                error_code=getattr(item, "error_code", "CORPUS_DISCOVERY_FAILED"),
                stage=getattr(item, "stage", "DISCOVERY"),
                message=getattr(item, "message", None),
            )
            for item in discovery_failures
        ]
        valid = 0
        duplicates = 0
        prepared: list[tuple[CorpusSourceFile, int, str, str]] = []
        deduplication = {
            "NEW": 0,
            "SAME_ID_SAME_CONTENT": 0,
            "SAME_ID_CHANGED_CONTENT": 0,
            "DUPLICATE_CONTENT_DIFFERENT_ID": 0,
            "CONFLICT": 0,
        }
        chunks = 0
        for identifier in identifiers:
            try:
                source = await self.reader.read_document(identifier)
                source_chunks, normalized_hash, external_id = self._validate_source(
                    source, config
                )
                prepared.append((source, source_chunks, normalized_hash, external_id))
            except (
                CorpusReaderError,
                CorpusNormalizationError,
                LegalChunkingError,
                ValueError,
            ) as exc:
                code = getattr(exc, "code", str(exc))
                failures.append(
                    CorpusFailureReport(
                        source_identifier=identifier,
                        error_code=code,
                        stage=(
                            "READ"
                            if isinstance(exc, CorpusReaderError)
                            else "VALIDATION"
                        ),
                    )
                )
                if fail_fast:
                    break

        persisted_by_identity: dict[tuple[str, str], CorpusDeduplicationRecord] = {}
        persisted_by_hash: dict[str, CorpusDeduplicationRecord] = {}
        lookup_failed = False
        if self.deduplication_lookup is not None and prepared:
            try:
                records = await self.deduplication_lookup.lookup(
                    identities=tuple(
                        (config.source_name, external_id)
                        for _, _, _, external_id in prepared
                    ),
                    normalized_content_hashes=tuple(
                        normalized_hash for _, _, normalized_hash, _ in prepared
                    ),
                )
                persisted_by_identity = {
                    (record.source_name, record.external_id): record
                    for record in records
                }
                persisted_by_hash = {
                    record.normalized_content_hash: record for record in records
                }
            except Exception:
                # A lookup outage must never silently classify every document
                # as NEW.  Expose only a stable, sanitized code.
                lookup_failed = True
                failures.append(
                    CorpusFailureReport(
                        source_identifier="<deduplication>",
                        error_code="CORPUS_DEDUP_LOOKUP_UNAVAILABLE",
                        stage="DEDUPLICATION",
                    )
                )

        seen_normalized_hashes: dict[str, str] = {}
        seen_identities: dict[tuple[str, str], str] = {}
        if not lookup_failed:
            for source, source_chunks, normalized_hash, external_id in prepared:
                identity = (config.source_name, external_id)
                persisted_identity = persisted_by_identity.get(identity)
                if identity in seen_identities:
                    outcome = (
                        "SAME_ID_SAME_CONTENT"
                        if seen_identities[identity] == normalized_hash
                        else "SAME_ID_CHANGED_CONTENT"
                    )
                elif persisted_identity is not None:
                    outcome = (
                        "SAME_ID_SAME_CONTENT"
                        if persisted_identity.normalized_content_hash == normalized_hash
                        else "SAME_ID_CHANGED_CONTENT"
                    )
                elif (
                    normalized_hash in seen_normalized_hashes
                    or normalized_hash in persisted_by_hash
                ):
                    outcome = "DUPLICATE_CONTENT_DIFFERENT_ID"
                else:
                    outcome = "NEW"
                deduplication[outcome] += 1
                seen_identities[identity] = normalized_hash
                seen_normalized_hashes.setdefault(normalized_hash, external_id)
                if outcome in {
                    "SAME_ID_SAME_CONTENT",
                    "DUPLICATE_CONTENT_DIFFERENT_ID",
                }:
                    duplicates += 1
                if chunks + source_chunks > config.max_chunks:
                    failures.append(
                        CorpusFailureReport(
                            source_identifier=source.source_identifier,
                            error_code="CORPUS_MAX_CHUNKS_EXCEEDED",
                            stage="CHUNK",
                            details={
                                "max_chunks": config.max_chunks,
                                "observed_chunks": chunks + source_chunks,
                            },
                        )
                    )
                    break
                chunks += source_chunks
                valid += 1
        run_id, request_id = self._correlation(identifiers, config)
        status: Literal["completed", "partial", "failed"] = (
            "completed" if not failures else "partial"
        )
        if (
            lookup_failed
            or any(
                failure.error_code == "CORPUS_MAX_CHUNKS_EXCEEDED"
                for failure in failures
            )
            or (fail_fast and failures)
        ):
            status = "failed"
        return CorpusDryRunReport(
            run_id=run_id,
            request_id=request_id,
            mode="execute" if execute else "dry-run",
            execution_mode="EXECUTE" if execute else "DRY_RUN",
            status=status,
            files_discovered=len(identifiers) + len(discovery_failures),
            files_valid=valid,
            files_invalid=len(failures),
            documents_new_estimate=deduplication["NEW"],
            documents_duplicate_estimate=duplicates,
            chunks_estimated=chunks,
            normalization_version=config.normalization_version,
            chunking_version=config.chunking_version,
            model=config.model,
            dimensions=config.dimensions,
            failures=failures,
            batch_size=config.batch_size,
            estimated_batch_count=ceil(chunks / config.batch_size) if chunks else 0,
            max_chunks=config.max_chunks,
            deduplication=deduplication,
        )

    def _validate_source(
        self, source: CorpusSourceFile, config: CorpusIngestionConfiguration
    ) -> tuple[int, str, str]:
        normalized = self.normalizer.normalize(
            source.text,
            config=replace(
                self.normalizer.config,
                version=config.normalization_version,
            ),
        )
        payload: Mapping[str, object] = dict(source.metadata or {})
        values = dict(payload)
        values.update(
            {
                "external_id": values.get(
                    "external_id", PurePosixPath(source.source_identifier).stem
                ),
                "source_name": values.get("source_name", config.source_name),
                "source_identifier": source.source_identifier,
                "document_type": values.get("document_type", config.document_type),
                "document_subtype": values.get(
                    "document_subtype", config.document_subtype
                ),
                "jurisdiction": values.get("jurisdiction", config.jurisdiction),
                "language": values.get("language", config.language),
                "normalization_version": config.normalization_version,
                "chunking_version": config.chunking_version,
            }
        )
        metadata = self.metadata_service.validate(values)
        chunks = self.chunker.chunk(
            normalized.normalized_content,
            chunking_version=config.chunking_version,
            normalization_version=config.normalization_version,
        )
        external_id = str(metadata.external_id)
        return len(chunks), normalized.normalized_content_hash, external_id

    @staticmethod
    def _correlation(
        identifiers: tuple[str, ...], config: CorpusIngestionConfiguration
    ) -> tuple[str, str]:
        payload = json.dumps(
            {
                "identifiers": identifiers,
                "configuration": {
                    key: value
                    for key, value in asdict(config).items()
                    if key not in {"batch_size", "max_chunks"}
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"dry-{digest[:32]}", digest[:32]


CorpusIngestion = CorpusIngestionService
