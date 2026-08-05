"""Pure domain objects and invariants for corpus ingestion/review."""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    REVIEWED = "REVIEWED"
    REJECTED = "REJECTED"


class ProvenanceType(StrEnum):
    AUTOMATED = "AUTOMATED"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"


class CorpusIngestionStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    PARSED = "PARSED"
    NORMALIZED = "NORMALIZED"
    VALIDATED = "VALIDATED"
    CHUNKED = "CHUNKED"
    EMBEDDING = "EMBEDDING"
    INDEXED = "INDEXED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CorpusDomainError(ValueError):
    """Base for sanitized corpus validation errors."""


class InvalidReviewTransitionError(CorpusDomainError):
    code = "INVALID_CORPUS_REVIEW_TRANSITION"


class ReviewVersionMismatchError(CorpusDomainError):
    code = "CORPUS_REVIEW_VERSION_MISMATCH"


class CorpusDocumentNotFoundError(CorpusDomainError):
    code = "CORPUS_DOCUMENT_NOT_FOUND"


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_embedding(vector: list[float], dimensions: int = 1024) -> None:
    if not vector:
        raise CorpusDomainError("EMBEDDING_VECTOR_EMPTY")
    if len(vector) != dimensions:
        raise CorpusDomainError("EMBEDDING_DIMENSIONS_MISMATCH")
    if not all(math.isfinite(value) for value in vector):
        raise CorpusDomainError("EMBEDDING_VECTOR_NON_FINITE")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CorpusDocument:
    id: uuid.UUID
    source_identifier: str
    raw_content: str = field(repr=False)
    normalized_content: str = field(repr=False)
    raw_content_hash: str = ""
    normalized_content_hash: str = ""
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    provenance_type: ProvenanceType = ProvenanceType.AUTOMATED
    review_version: int = 1
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = field(default=None, repr=False)
    ingestion_status: CorpusIngestionStatus = CorpusIngestionStatus.DISCOVERED
    # Persistence metadata is optional for backwards-compatible construction of
    # the pure entity.  Repository mappers populate it when loading a full row.
    external_id: str = ""
    source_name: str = ""
    title: str | None = None
    document_type: str = "decreto"
    document_subtype: str = "designacion_transitoria"
    jurisdiction: str = "nacion"
    language: str = "es"
    organization: str | None = None
    source_url: str | None = None
    publication_date: date | None = None
    metadata: dict[str, object] = field(default_factory=dict, repr=False)
    normalization_version: str = "005-nfc-v1"
    chunking_version: str = "005-legal-v1"
    active_generation: int | None = None

    def __post_init__(self) -> None:
        if not self.raw_content.strip():
            raise CorpusDomainError("CORPUS_RAW_CONTENT_EMPTY")
        if self.ingestion_status not in {
            CorpusIngestionStatus.DISCOVERED,
            CorpusIngestionStatus.FAILED,
        } and not self.normalized_content.strip():
            raise CorpusDomainError("CORPUS_NORMALIZED_CONTENT_EMPTY")
        if self.review_version <= 0:
            raise CorpusDomainError("CORPUS_REVIEW_VERSION_INVALID")
        if not _HASH_RE.fullmatch(self.raw_content_hash) or not _HASH_RE.fullmatch(
            self.normalized_content_hash
        ):
            raise CorpusDomainError("CORPUS_CONTENT_HASH_INVALID")
        if self.review_status is ReviewStatus.PENDING_REVIEW and (
            self.reviewed_by is not None or self.reviewed_at is not None
        ):
            raise CorpusDomainError("CORPUS_REVIEW_METADATA_INVALID")
        if self.review_status is not ReviewStatus.PENDING_REVIEW and (
            not self.reviewed_by or self.reviewed_at is None
        ):
            raise CorpusDomainError("CORPUS_REVIEW_METADATA_INVALID")
        if self.review_status in {ReviewStatus.REVIEWED, ReviewStatus.REJECTED} and (
            self.provenance_type is not ProvenanceType.HUMAN_REVIEWED
        ):
            raise CorpusDomainError("CORPUS_REVIEW_PROVENANCE_INVALID")
        if self.review_status is ReviewStatus.REJECTED and not self._clean_note(
            self.review_notes
        ):
            raise CorpusDomainError("CORPUS_REVIEW_REASON_REQUIRED")

    @staticmethod
    def _clean_note(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned[:1000] if cleaned else None

    def transition_ingestion(self, status: CorpusIngestionStatus) -> None:
        allowed: dict[CorpusIngestionStatus, set[CorpusIngestionStatus]] = {
            CorpusIngestionStatus.DISCOVERED: {
                CorpusIngestionStatus.PARSED,
                CorpusIngestionStatus.FAILED,
            },
            CorpusIngestionStatus.PARSED: {
                CorpusIngestionStatus.NORMALIZED,
                CorpusIngestionStatus.FAILED,
            },
            CorpusIngestionStatus.NORMALIZED: {
                CorpusIngestionStatus.VALIDATED,
                CorpusIngestionStatus.FAILED,
            },
            CorpusIngestionStatus.VALIDATED: {
                CorpusIngestionStatus.CHUNKED,
                CorpusIngestionStatus.FAILED,
            },
            CorpusIngestionStatus.CHUNKED: {
                CorpusIngestionStatus.EMBEDDING,
                CorpusIngestionStatus.FAILED,
            },
            CorpusIngestionStatus.EMBEDDING: {
                CorpusIngestionStatus.INDEXED,
                CorpusIngestionStatus.FAILED,
            },
            CorpusIngestionStatus.INDEXED: {
                CorpusIngestionStatus.COMPLETED,
                CorpusIngestionStatus.FAILED,
            },
            CorpusIngestionStatus.COMPLETED: set(),
            CorpusIngestionStatus.FAILED: set(),
        }
        if status not in allowed[self.ingestion_status]:
            raise CorpusDomainError("CORPUS_INGESTION_TRANSITION_INVALID")
        if status not in {
            CorpusIngestionStatus.DISCOVERED,
            CorpusIngestionStatus.FAILED,
        } and not self.normalized_content.strip():
            raise CorpusDomainError("CORPUS_NORMALIZED_CONTENT_EMPTY")
        self.ingestion_status = status

    def transition_review(
        self,
        status: ReviewStatus,
        *,
        expected_version: int,
        expected_status: ReviewStatus = ReviewStatus.PENDING_REVIEW,
        reviewed_by: str,
        reviewed_at: datetime,
        review_notes: str | None = None,
    ) -> None:
        if expected_version <= 0:
            raise ReviewVersionMismatchError("CORPUS_REVIEW_VERSION_INVALID")
        if expected_version != self.review_version:
            raise ReviewVersionMismatchError("CORPUS_REVIEW_VERSION_MISMATCH")
        if self.review_status != expected_status or self.review_status in {
            ReviewStatus.REVIEWED,
            ReviewStatus.REJECTED,
        }:
            raise InvalidReviewTransitionError("INVALID_CORPUS_REVIEW_TRANSITION")
        if not reviewed_by.strip() or status not in {
            ReviewStatus.REVIEWED,
            ReviewStatus.REJECTED,
        }:
            raise InvalidReviewTransitionError("INVALID_CORPUS_REVIEW_TRANSITION")
        cleaned_notes = self._clean_note(review_notes)
        if status is ReviewStatus.REJECTED and cleaned_notes is None:
            raise InvalidReviewTransitionError("CORPUS_REVIEW_REASON_REQUIRED")
        if reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=UTC)
        self.review_status = status
        self.provenance_type = ProvenanceType.HUMAN_REVIEWED
        self.reviewed_by = reviewed_by.strip()[:200]
        self.reviewed_at = reviewed_at
        self.review_notes = cleaned_notes
        self.review_version += 1


@dataclass(frozen=True, slots=True)
class CorpusDocumentUpsertResult:
    """Stable result returned by the document upsert port."""

    status: Literal["CREATED", "UNCHANGED", "UPDATED"]
    document: CorpusDocument
    changed_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CorpusDeduplicationRecord:
    """Minimal persisted identity/hash data used by dry-run lookup."""

    source_name: str
    external_id: str
    normalized_content_hash: str


@dataclass(frozen=True, slots=True)
class CorpusChunk:
    id: uuid.UUID
    document_id: uuid.UUID
    content: str = field(repr=False)
    content_hash: str
    generation: int
    section_index: int
    paragraph_index: int | None
    embedding: tuple[float, ...] | None = field(default=None, repr=False)
    section_type: str = "UNKNOWN"
    article_number: str | None = None
    token_count: int = 0
    chunking_version: str = "005-legal-v1"
    normalization_version: str = "005-nfc-v1"
    state: str = "STAGED"
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    metadata: dict[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise CorpusDomainError("CORPUS_CHUNK_CONTENT_EMPTY")
        if (
            self.generation <= 0
            or self.section_index < 0
            or (self.paragraph_index is not None and self.paragraph_index < 0)
            or self.token_count < 0
        ):
            raise CorpusDomainError("CORPUS_CHUNK_INDEX_INVALID")
        if self.state not in {"STAGED", "EMBEDDING", "ACTIVE", "FAILED", "SUPERSEDED"}:
            raise CorpusDomainError("CORPUS_CHUNK_STATE_INVALID")
        if not _HASH_RE.fullmatch(self.content_hash):
            raise CorpusDomainError("CORPUS_CHUNK_HASH_INVALID")
        if self.state == "ACTIVE" and self.embedding is None:
            raise CorpusDomainError("CORPUS_ACTIVE_CHUNK_EMBEDDING_REQUIRED")
        if self.embedding is not None:
            validate_embedding(list(self.embedding))
            if not self.embedding_model or self.embedding_dimensions != 1024:
                raise CorpusDomainError("CORPUS_CHUNK_EMBEDDING_METADATA_INVALID")
