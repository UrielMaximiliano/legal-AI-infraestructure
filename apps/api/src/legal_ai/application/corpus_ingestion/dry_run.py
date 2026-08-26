"""Dry-run del corpus: validación local y clasificación de duplicados.

No abre UnitOfWork: todo el análisis es de sólo lectura sobre el corpus.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from math import ceil
from typing import Any, Literal

from legal_ai.adapters.filesystem_corpus import CorpusReaderError
from legal_ai.application.corpus_ingestion.configuration import (
    CorpusIngestionConfiguration,
)
from legal_ai.application.corpus_ingestion.preparation import DocumentPreparer
from legal_ai.application.corpus_normalization import CorpusNormalizationError
from legal_ai.application.legal_chunking import LegalChunkingError
from legal_ai.domain.corpus import CorpusDeduplicationRecord
from legal_ai.ports.corpus_repositories import CorpusDeduplicationLookupPort
from legal_ai.schemas.corpus_cli import CorpusDryRunReport, CorpusFailureReport


def discovery_failure_reports(
    discovery_failures: tuple[object, ...],
) -> list[CorpusFailureReport]:
    """Normaliza las fallas de descubrimiento a reportes sanitizados."""

    return [
        CorpusFailureReport(
            source_identifier=getattr(item, "source_identifier", "<invalid-source>"),
            error_code=getattr(item, "error_code", "CORPUS_DISCOVERY_FAILED"),
            stage=getattr(item, "stage", "DISCOVERY"),
            message=getattr(item, "message", None),
        )
        for item in discovery_failures
    ]


def correlation(
    identifiers: tuple[str, ...], config: CorpusIngestionConfiguration
) -> tuple[str, str]:
    """run_id/request_id deterministas para ejecuciones sin run explícito."""

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


async def process_dry_run(
    reader: Any,
    preparer: DocumentPreparer,
    *,
    identifiers: tuple[str, ...],
    config: CorpusIngestionConfiguration,
    execute: bool,
    fail_fast: bool,
    deduplication_lookup: CorpusDeduplicationLookupPort | None,
    discovery_failures: tuple[object, ...] = (),
) -> CorpusDryRunReport:
    failures: list[CorpusFailureReport] = discovery_failure_reports(discovery_failures)
    valid = 0
    duplicates = 0
    prepared: list[tuple[Any, int, str, str]] = []
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
            source = await reader.read_document(identifier)
            source_chunks, normalized_hash, external_id = preparer.validate_source(
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
                        "READ" if isinstance(exc, CorpusReaderError) else "VALIDATION"
                    ),
                )
            )
            if fail_fast:
                break

    persisted_by_identity: dict[tuple[str, str], CorpusDeduplicationRecord] = {}
    persisted_by_hash: dict[str, CorpusDeduplicationRecord] = {}
    lookup_failed = False
    if deduplication_lookup is not None and prepared:
        try:
            records = await deduplication_lookup.lookup(
                identities=tuple(
                    (config.source_name, external_id)
                    for _, _, _, external_id in prepared
                ),
                normalized_content_hashes=tuple(
                    normalized_hash for _, _, normalized_hash, _ in prepared
                ),
            )
            persisted_by_identity = {
                (record.source_name, record.external_id): record for record in records
            }
            persisted_by_hash = {
                record.normalized_content_hash: record for record in records
            }
        except Exception:
            # Una caída del lookup nunca debe clasificar todo como NEW
            # en silencio; se expone sólo un código estable y sanitizado.
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
    run_id, request_id = correlation(identifiers, config)
    status: Literal["completed", "partial", "failed"] = (
        "completed" if not failures else "partial"
    )
    if (
        lookup_failed
        or any(
            failure.error_code == "CORPUS_MAX_CHUNKS_EXCEEDED" for failure in failures
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
