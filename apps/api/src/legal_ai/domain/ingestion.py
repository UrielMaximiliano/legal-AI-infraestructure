"""Domain state for ingestion runs and embedding batches."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class IngestionRunType(StrEnum):
    INGEST = "INGEST"
    REINDEX = "REINDEX"


class IngestionRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class EmbeddingBatchStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


class IngestionRunTransitionError(ValueError):
    """Stable, sanitized error for invalid run state changes."""

    code = "INVALID_INGESTION_RUN_TRANSITION"


_TERMINAL_RUN_STATUSES = frozenset(
    {
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.PARTIAL,
        IngestionRunStatus.FAILED,
    }
)
_RUN_TRANSITIONS: dict[IngestionRunStatus, frozenset[IngestionRunStatus]] = {
    IngestionRunStatus.PENDING: frozenset({IngestionRunStatus.RUNNING}),
    IngestionRunStatus.RUNNING: frozenset(
        {
            IngestionRunStatus.COMPLETED,
            IngestionRunStatus.PARTIAL,
            IngestionRunStatus.FAILED,
            IngestionRunStatus.INTERRUPTED,
        }
    ),
    IngestionRunStatus.INTERRUPTED: frozenset({IngestionRunStatus.RUNNING}),
    IngestionRunStatus.COMPLETED: frozenset(),
    IngestionRunStatus.PARTIAL: frozenset(),
    IngestionRunStatus.FAILED: frozenset(),
}
_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")


def _as_utc(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


_CONFIGURATION_KEYS = frozenset(
    {
        "model",
        "dimensions",
        "source_name",
        "document_type",
        "document_subtype",
        "jurisdiction",
        "language",
        "normalization_version",
        "chunking_version",
        "batch_size",
        "max_chunks",
    }
)
_COUNT_KEYS = frozenset(
    {
        "discovered_count",
        "parsed_count",
        "normalized_count",
        "validated_count",
        "chunked_count",
        "failed_count",
        "embedded_count",
        "indexed_count",
    }
)


def _sanitize_configuration_snapshot(
    snapshot: dict[str, object],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in snapshot.items():
        if key not in _CONFIGURATION_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    return result


def sanitize_configuration_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    """Allowlist run configuration fields before writing JSONB."""

    return _sanitize_configuration_snapshot(snapshot)


def _configuration_hash(snapshot: dict[str, object]) -> str:
    payload = json.dumps(
        _sanitize_configuration_snapshot(snapshot),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def configuration_hash_for_snapshot(snapshot: dict[str, object]) -> str:
    """Return the reproducible hash for a sanitized run configuration."""

    return _configuration_hash(snapshot)


def _normalize_counts(
    counts: dict[str, int], *, processed_documents: int, processed_chunks: int
) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key, value in counts.items():
        if key not in _COUNT_KEYS:
            continue
        if type(value) is not int or value < 0:
            raise ValueError("INGESTION_RUN_COUNTS_INVALID")
        normalized[key] = value
    normalized.setdefault("parsed_count", processed_documents)
    normalized.setdefault("chunked_count", processed_chunks)
    return normalized


@dataclass(slots=True)
class IngestionRun:
    id: uuid.UUID
    run_id: str
    run_type: IngestionRunType
    status: IngestionRunStatus = IngestionRunStatus.PENDING
    processed_documents: int = 0
    processed_chunks: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    resumed_at: datetime | None = None
    resume_count: int = 0
    error_code: str | None = field(default=None, repr=False)
    # Persistence metadata belongs to the ingestion aggregate.  Defaults are
    # deterministic compatibility values for callers created before 005; the
    # repository never invents a fixed source or configuration value.
    source_identifier: str = ""
    configuration_hash: str = ""
    configuration_snapshot: dict[str, object] = field(default_factory=dict, repr=False)
    counts: dict[str, int] = field(default_factory=dict, repr=False)
    heartbeat_at: datetime | None = None
    error_summary: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_type, IngestionRunType) or not isinstance(
            self.status, IngestionRunStatus
        ):
            raise ValueError("INGESTION_RUN_STATE_INVALID")
        if not self.run_id.strip() or len(self.run_id) > 128:
            raise ValueError("INGESTION_RUN_ID_INVALID")
        if (
            self.processed_documents < 0
            or self.processed_chunks < 0
            or self.resume_count < 0
        ):
            raise ValueError("INGESTION_RUN_COUNTS_INVALID")
        for attribute in ("started_at", "finished_at", "resumed_at"):
            value = getattr(self, attribute)
            if value is not None:
                setattr(self, attribute, _as_utc(value))
        if self.status in _TERMINAL_RUN_STATUSES and self.finished_at is None:
            raise ValueError("INGESTION_RUN_FINISHED_AT_INVALID")
        if self.status not in _TERMINAL_RUN_STATUSES and self.finished_at is not None:
            raise ValueError("INGESTION_RUN_FINISHED_AT_INVALID")
        if self.error_code is not None:
            self.error_code = self._validate_error_code(self.error_code)
        if self.source_identifier and not self.source_identifier.strip():
            raise ValueError("INGESTION_SOURCE_IDENTIFIER_INVALID")
        if len(self.source_identifier) > 512:
            raise ValueError("INGESTION_SOURCE_IDENTIFIER_INVALID")
        if self.configuration_snapshot:
            self.configuration_snapshot = _sanitize_configuration_snapshot(
                self.configuration_snapshot
            )
        if self.configuration_hash and not re.fullmatch(
            r"[0-9a-f]{64}", self.configuration_hash
        ):
            raise ValueError("INGESTION_CONFIGURATION_HASH_INVALID")
        self.counts = _normalize_counts(
            self.counts,
            processed_documents=self.processed_documents,
            processed_chunks=self.processed_chunks,
        )
        if self.heartbeat_at is not None:
            self.heartbeat_at = _as_utc(self.heartbeat_at)
        if self.error_summary is not None:
            self.error_summary = " ".join(self.error_summary.split())[:500] or None

    @staticmethod
    def _validate_error_code(error_code: str) -> str:
        if not isinstance(error_code, str) or not _ERROR_CODE_RE.fullmatch(error_code):
            raise ValueError("INGESTION_RUN_ERROR_CODE_INVALID")
        return error_code

    def _validate_transition(self, status: IngestionRunStatus) -> None:
        if not isinstance(status, IngestionRunStatus):
            raise IngestionRunTransitionError(IngestionRunTransitionError.code)
        if status not in _RUN_TRANSITIONS[self.status]:
            raise IngestionRunTransitionError(IngestionRunTransitionError.code)

    def _transition(self, status: IngestionRunStatus) -> None:
        self._validate_transition(status)
        self.status = status

    def start(self, *, at: datetime | None = None) -> None:
        self._transition(IngestionRunStatus.RUNNING)
        if self.started_at is None:
            self.started_at = _as_utc(at)

    def finish(
        self,
        status: IngestionRunStatus,
        *,
        at: datetime | None = None,
        error_code: str | None = None,
    ) -> None:
        self._validate_transition(status)
        next_error_code = self.error_code
        if error_code is not None:
            next_error_code = self._validate_error_code(error_code)
        if (
            status
            in {
                IngestionRunStatus.FAILED,
                IngestionRunStatus.INTERRUPTED,
            }
            and next_error_code is None
        ):
            raise ValueError("INGESTION_RUN_ERROR_CODE_REQUIRED")
        next_finished_at = _as_utc(at) if status in _TERMINAL_RUN_STATUSES else None

        self.status = status
        self.error_code = next_error_code
        self.finished_at = next_finished_at

    def resume(self, *, at: datetime | None = None) -> None:
        if self.status is not IngestionRunStatus.INTERRUPTED:
            raise IngestionRunTransitionError(IngestionRunTransitionError.code)
        self._validate_transition(IngestionRunStatus.RUNNING)
        next_resumed_at = _as_utc(at)
        next_resume_count = self.resume_count + 1

        self.status = IngestionRunStatus.RUNNING
        self.resumed_at = next_resumed_at
        self.resume_count = next_resume_count

    def to_safe_dict(self) -> dict[str, object]:
        """Return the explicit persistence/audit-safe run representation."""

        return {
            "id": str(self.id),
            "run_id": self.run_id,
            "run_type": self.run_type.value,
            "status": self.status.value,
            "processed_documents": self.processed_documents,
            "processed_chunks": self.processed_chunks,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "resumed_at": self.resumed_at.isoformat() if self.resumed_at else None,
            "resume_count": self.resume_count,
            "error_code": self.error_code,
            "source_identifier": self.source_identifier,
            "configuration_hash": self.configuration_hash,
            "configuration_snapshot": dict(self.configuration_snapshot),
            "counts": dict(self.counts),
            "heartbeat_at": (
                self.heartbeat_at.isoformat() if self.heartbeat_at else None
            ),
            "error_summary": self.error_summary,
        }


@dataclass(frozen=True, slots=True)
class IngestionFailure:
    id: uuid.UUID
    ingestion_run_id: uuid.UUID
    stage: str
    error_code: str
    message: str
    retryable: bool = False
    source_identifier: str | None = None
    document_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.stage.strip() or not self.error_code.strip():
            raise ValueError("INGESTION_FAILURE_METADATA_INVALID")
        if not self.message.strip() or len(self.message) > 500:
            raise ValueError("INGESTION_FAILURE_MESSAGE_INVALID")
        if self.source_identifier is not None and (
            not self.source_identifier.strip() or len(self.source_identifier) > 512
        ):
            raise ValueError("INGESTION_SOURCE_IDENTIFIER_INVALID")


@dataclass(slots=True)
class EmbeddingBatch:
    id: uuid.UUID
    ingestion_run_id: uuid.UUID
    generation: int
    batch_index: int
    input_count: int
    status: EmbeddingBatchStatus = EmbeddingBatchStatus.PENDING
    chunk_ids: tuple[uuid.UUID, ...] = ()
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_dimensions: int = 1024
    attempt_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            self.generation <= 0
            or self.batch_index < 0
            or self.input_count < 0
            or self.embedding_dimensions != 1024
            or self.attempt_count < 0
        ):
            raise ValueError("EMBEDDING_BATCH_INVALID")

    def transition(self, status: EmbeddingBatchStatus) -> None:
        allowed = {
            EmbeddingBatchStatus.PENDING: {
                EmbeddingBatchStatus.PROCESSING,
                EmbeddingBatchStatus.FAILED_RETRYABLE,
            },
            EmbeddingBatchStatus.PROCESSING: {
                EmbeddingBatchStatus.SUCCEEDED,
                EmbeddingBatchStatus.FAILED_RETRYABLE,
                EmbeddingBatchStatus.FAILED_FINAL,
            },
            EmbeddingBatchStatus.FAILED_RETRYABLE: {
                EmbeddingBatchStatus.PROCESSING,
                EmbeddingBatchStatus.FAILED_FINAL,
            },
            EmbeddingBatchStatus.SUCCEEDED: set(),
            EmbeddingBatchStatus.FAILED_FINAL: set(),
        }
        if status not in allowed[self.status]:
            raise ValueError("EMBEDDING_BATCH_STATUS_INVALID")
        self.status = status
