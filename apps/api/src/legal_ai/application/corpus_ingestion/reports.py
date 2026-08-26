"""Construcción de reportes del modo EXECUTE a partir del run persistido."""

from __future__ import annotations

from legal_ai.application.corpus_ingestion.configuration import (
    CorpusIngestionConfiguration,
)
from legal_ai.domain.ingestion import IngestionRun, IngestionRunStatus
from legal_ai.schemas.corpus_cli import CorpusDryRunReport, CorpusFailureReport


def execution_report(
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
