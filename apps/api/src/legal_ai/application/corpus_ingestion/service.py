"""Orquestador del pipeline de ingesta 005 (dry-run y ejecución)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from legal_ai.adapters.filesystem_corpus import FilesystemCorpusReader
from legal_ai.application.corpus_ingestion.configuration import (
    CorpusIngestionConfiguration,
    configuration_snapshot,
    limit_identifiers,
)
from legal_ai.application.corpus_ingestion.dry_run import (
    discovery_failure_reports,
    process_dry_run,
)
from legal_ai.application.corpus_ingestion.embedding_batches import (
    default_coordinator,
    default_provider,
    interrupt_run,
    mark_batch_processing,
    pending_batches,
    persist_batch_failure,
    persist_batch_success,
)
from legal_ai.application.corpus_ingestion.finalization import finalize_execution
from legal_ai.application.corpus_ingestion.preparation import (
    DocumentPreparer,
    PreparedDocument,
    error_code,
)
from legal_ai.application.corpus_ingestion.reports import execution_report
from legal_ai.application.corpus_ingestion.staging import (
    open_or_resume_run,
    prepare_documents,
    resume_staged,
    stage_documents,
)
from legal_ai.application.corpus_metadata import CorpusMetadataService
from legal_ai.application.corpus_normalization import CorpusNormalizationService
from legal_ai.application.embedding_batch import EmbeddingBatchProcessor
from legal_ai.application.legal_chunking import LegalChunkingService
from legal_ai.domain.ingestion import configuration_hash_for_snapshot
from legal_ai.ports.corpus_repositories import CorpusDeduplicationLookupPort
from legal_ai.ports.embedding import EmbeddingProvider, InferenceCoordinationPort
from legal_ai.schemas.corpus_cli import CorpusDryRunReport, CorpusFailureReport


def _default_uow_factory() -> Any:
    # Resolución diferida: el dry-run no debe exigir los adaptadores de DB.
    from legal_ai.adapters.database.unit_of_work import UnitOfWork

    return UnitOfWork


class CorpusIngestionService:
    """Mantiene el parseo pesado fuera de las transacciones; dry-run sin UoW."""

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
        self._preparer = DocumentPreparer(
            normalizer=self.normalizer,
            metadata_service=self.metadata_service,
            chunker=self.chunker,
        )
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
        config = _validated(configuration)
        discovery = await self.reader.discover_report(root, fail_fast=fail_fast)
        identifiers = limit_identifiers(discovery.files, limit)
        return await process_dry_run(
            self.reader,
            self._preparer,
            identifiers=identifiers,
            config=config,
            execute=False,
            fail_fast=fail_fast,
            deduplication_lookup=self.deduplication_lookup,
            discovery_failures=discovery.failures,
        )

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
        """Ejecuta el pipeline. Sin ``execute`` es estrictamente dry-run."""

        if execute:
            return await self._execute(
                root,
                configuration=configuration,
                limit=limit,
                fail_fast=fail_fast,
                run_id=run_id,
                resume=resume,
            )
        return await self.dry_run(
            root, configuration=configuration, limit=limit, fail_fast=fail_fast
        )

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
        """Ejecuta la ingesta con transacciones cortas alrededor de inferencia."""

        config = _validated(configuration)
        if run_id is not None and (not run_id.strip() or len(run_id) > 128):
            raise ValueError("INGESTION_RUN_ID_INVALID")
        if resume and run_id is None:
            raise ValueError("CORPUS_RESUME_REQUIRES_RUN_ID")
        effective_run_id = run_id or f"ingest-{uuid.uuid4().hex}"
        discovery = await self.reader.discover_report(root, fail_fast=fail_fast)
        identifiers = limit_identifiers(discovery.files, limit)
        failures = discovery_failure_reports(discovery.failures)

        prepared, validation_failures = await prepare_documents(
            self.reader,
            self._preparer,
            identifiers,
            config,
            fail_fast=fail_fast,
        )
        failures.extend(validation_failures)

        snapshot = configuration_snapshot(config)
        configuration_hash = configuration_hash_for_snapshot(snapshot)
        uow_factory = self._uow_factory or _default_uow_factory()

        staged: list[tuple[PreparedDocument, int, tuple[uuid.UUID, ...]]] = []
        async with uow_factory() as uow:
            run, finished_report = await open_or_resume_run(
                uow,
                effective_run_id=effective_run_id,
                config=config,
                snapshot=snapshot,
                configuration_hash=configuration_hash,
                identifiers=identifiers,
                prepared=prepared,
                failures=failures,
                resume=resume,
            )
            if finished_report is not None:
                return finished_report
            staged = await stage_documents(uow, run, prepared, config)
            run.counts["failed_count"] = len(failures)
            await uow.ingestion_runs.update(run)

        if resume and not staged:
            staged = await resume_staged(effective_run_id, uow_factory)

        provider = self.embedding_provider or default_provider(config)
        coordinator = self.inference_coordinator or default_coordinator()
        try:
            batches = await pending_batches(effective_run_id, uow_factory, staged)
            failed = False
            batch_processor = EmbeddingBatchProcessor(
                provider,
                coordinator,
                dimensions=config.dimensions,
                timeout_seconds=30.0,
            )
            for batch in batches:
                try:
                    texts = await mark_batch_processing(batch, uow_factory)
                    vectors = await batch_processor.embed(texts)
                    await persist_batch_success(batch, vectors, uow_factory)
                except asyncio.CancelledError:
                    await interrupt_run(effective_run_id, uow_factory)
                    raise
                except Exception as exc:  # errores de proveedor/batch sanitizados
                    failed = True
                    batch_error_code = error_code(exc, "EMBEDDING_BATCH_FAILED")
                    await persist_batch_failure(batch, batch_error_code, uow_factory)
                    failures.append(
                        CorpusFailureReport(
                            source_identifier="<embedding>",
                            error_code=batch_error_code,
                            stage="EMBEDDING",
                        )
                    )
                    if fail_fast:
                        break

            finalized = await finalize_execution(
                effective_run_id,
                staged,
                failed or bool(failures),
                failures,
                uow_factory,
            )
        finally:
            if self.inference_coordinator is None and hasattr(coordinator, "close"):
                await coordinator.close()
        return execution_report(
            effective_run_id, identifiers, failures, finalized, config
        )


def _validated(
    configuration: CorpusIngestionConfiguration | None,
) -> CorpusIngestionConfiguration:
    config = configuration or CorpusIngestionConfiguration()
    config.validate()
    return config


CorpusIngestion = CorpusIngestionService

__all__ = [
    "CorpusIngestion",
    "CorpusIngestionConfiguration",
    "CorpusIngestionService",
]
