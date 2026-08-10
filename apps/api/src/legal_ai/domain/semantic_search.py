"""Minimized search audit and human evaluation domain objects."""

from __future__ import annotations

import math
import re
import unicodedata
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS

MAX_TOP_K = 50
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_REVIEW_STATUSES = {"PENDING_REVIEW", "REVIEWED"}
_REQUIRED_FILTER_KEYS = frozenset({"document_type", "document_subtype", "jurisdiction"})
ALLOWED_FILTER_KEYS = frozenset(
    {
        "document_type",
        "document_subtype",
        "jurisdiction",
        "language",
        "organization",
        "review_status",
    }
)
_FILTER_LIMITS = {
    "document_type": 50,
    "document_subtype": 100,
    "jurisdiction": 120,
    "language": 16,
    "organization": 200,
    "review_status": 20,
}
_SENSITIVE_FILTER_VALUE_RE = re.compile(
    r"(?:authorization|bearer|token|raw[_ ]?content|normalized[_ ]?content|"
    r"storage[_ ]?path|embedding|vector|\bquery\b)",
    re.IGNORECASE,
)


class SemanticSearchStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SemanticSearchCandidate(Mapping[str, object]):
    """Public, ORM-free search result allowlist."""

    document_id: uuid.UUID
    chunk_id: uuid.UUID
    external_id: str
    source_name: str
    document_type: str
    document_subtype: str
    jurisdiction: str
    language: str
    section_type: str
    article_number: str | None
    excerpt: str
    chunk_index: int
    similarity_score: float
    generation: int
    organization: str | None = None
    title: str | None = None
    publication_date: str | None = None
    source_url: str | None = None
    content_hash: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def id(self) -> uuid.UUID:
        """Compatibility alias for the historical tuple result."""

        return self.chunk_id

    @property
    def score(self) -> float:
        return self.similarity_score

    def _as_dict(self) -> dict[str, object]:
        return {
            "document_id": str(self.document_id),
            "chunk_id": str(self.chunk_id),
            "external_id": self.external_id,
            "source_name": self.source_name,
            "title": self.title,
            "document_type": self.document_type,
            "document_subtype": self.document_subtype,
            "jurisdiction": self.jurisdiction,
            "language": self.language,
            "organization": self.organization,
            "section_type": self.section_type,
            "article_number": self.article_number,
            "excerpt": self.excerpt,
            "chunk_index": self.chunk_index,
            "similarity_score": self.similarity_score,
            "generation": self.generation,
            "publication_date": self.publication_date,
            "source_url": self.source_url,
            "metadata": {
                str(key): value
                for key, value in self.metadata.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            },
        }

    def __getitem__(self, key: str | int) -> object:
        if isinstance(key, int):
            if key == 0:
                return self
            if key == 2:
                return self.similarity_score
            raise IndexError(key)
        return self._as_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._as_dict())

    def __len__(self) -> int:
        return len(self._as_dict())


def _sanitize(value: str, maximum: int) -> str:
    cleaned = "".join(character if ord(character) >= 32 else " " for character in value)
    return " ".join(cleaned.split())[:maximum]


def _invalid_filters() -> ValueError:
    return ValueError("INVALID_SEMANTIC_SEARCH_FILTERS")


def _canonical_code(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.casefold()).strip("_")


def _normalize_filter_value(key: str, value: object) -> str:
    if type(value) is not str:
        raise _invalid_filters()
    maximum = _FILTER_LIMITS[key]
    cleaned = _sanitize(value, maximum + 1)
    if not cleaned or len(cleaned) > maximum:
        raise _invalid_filters()
    if _SENSITIVE_FILTER_VALUE_RE.search(cleaned):
        raise _invalid_filters()

    if key in {"document_type", "document_subtype", "jurisdiction", "language"}:
        cleaned = _canonical_code(cleaned)
    elif key == "review_status":
        cleaned = cleaned.upper()

    allowed_values = {
        "document_type": {"decreto"},
        "document_subtype": {"designacion_transitoria"},
        "jurisdiction": {"nacion"},
        "review_status": _ALLOWED_REVIEW_STATUSES,
    }
    if key in allowed_values and cleaned not in allowed_values[key]:
        raise _invalid_filters()
    return cleaned


def _validate_sanitized_filters(filters: object) -> dict[str, str]:
    if type(filters) is not dict:
        raise _invalid_filters()
    keys = set(filters)
    if not _REQUIRED_FILTER_KEYS.issubset(keys) or not keys.issubset(
        ALLOWED_FILTER_KEYS
    ):
        raise _invalid_filters()
    return {key: _normalize_filter_value(key, value) for key, value in filters.items()}


@dataclass(frozen=True, slots=True)
class SearchFilters:
    document_type: str | None = None
    document_subtype: str | None = None
    jurisdiction: str | None = None
    language: str | None = None
    review_status: str | None = None
    organization: str | None = None
    reviewed_only: bool = True

    def __post_init__(self) -> None:
        if type(self.reviewed_only) is not bool:
            raise _invalid_filters()
        values: dict[str, object] = {
            "document_type": self.document_type,
            "document_subtype": self.document_subtype,
            "jurisdiction": self.jurisdiction,
        }
        for key in ("language", "organization", "review_status"):
            value = getattr(self, key)
            if value is not None:
                values[key] = value
        normalized = _validate_sanitized_filters(values)
        review_status = normalized.get("review_status")
        if self.reviewed_only and review_status not in {None, "REVIEWED"}:
            raise _invalid_filters()
        if not self.reviewed_only and review_status is None:
            raise _invalid_filters()
        for key, value in normalized.items():
            object.__setattr__(self, key, value)

    def sanitized(self) -> dict[str, str]:
        # ``reviewed_only`` is an execution policy, not an audit filter.  The
        # effective ``review_status=REVIEWED`` below is sufficient to preserve
        # the default without persisting an uncontracted key.
        result = {
            "document_type": self.document_type,
            "document_subtype": self.document_subtype,
            "jurisdiction": self.jurisdiction,
        }
        for key in ("language", "organization"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        effective_status = self.review_status
        if effective_status is None and self.reviewed_only:
            effective_status = "REVIEWED"
        if effective_status:
            result["review_status"] = effective_status
        return _validate_sanitized_filters(result)


@dataclass(frozen=True, slots=True)
class SemanticSearchRun:
    id: uuid.UUID
    query_hash: str
    filters_sanitized: dict[str, str]
    top_k: int
    minimum_score: float | None
    embedding_model: str
    embedding_dimensions: int
    result_count: int
    duration_ms: int
    status: SemanticSearchStatus | str
    request_id: str
    error_code: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not _HASH_RE.fullmatch(self.query_hash):
            raise ValueError("SEMANTIC_SEARCH_QUERY_HASH_INVALID")
        if type(self.top_k) is not int or not 0 < self.top_k <= MAX_TOP_K:
            raise ValueError("SEMANTIC_SEARCH_TOP_K_INVALID")
        if self.minimum_score is not None and (
            type(self.minimum_score) not in {int, float}
            or not math.isfinite(self.minimum_score)
            or not 0 <= self.minimum_score <= 1
        ):
            raise ValueError("SEMANTIC_SEARCH_SCORE_INVALID")
        if not self.embedding_model.strip():
            raise ValueError("SEMANTIC_SEARCH_MODEL_INVALID")
        if self.embedding_dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError("EMBEDDING_DIMENSIONS_MISMATCH")
        if self.result_count < 0 or self.duration_ms < 0:
            raise ValueError("SEMANTIC_SEARCH_COUNTS_INVALID")
        try:
            status = SemanticSearchStatus(self.status)
        except ValueError as exc:
            raise ValueError("SEMANTIC_SEARCH_STATUS_INVALID") from exc
        object.__setattr__(self, "status", status)
        if status is SemanticSearchStatus.SUCCEEDED and self.error_code is not None:
            raise ValueError("SEMANTIC_SEARCH_ERROR_CODE_INVALID")
        if status is SemanticSearchStatus.FAILED:
            if self.error_code is None:
                raise ValueError("SEMANTIC_SEARCH_ERROR_CODE_INVALID")
            sanitized_error = _sanitize(self.error_code, 80)
            if not sanitized_error:
                raise ValueError("SEMANTIC_SEARCH_ERROR_CODE_INVALID")
            object.__setattr__(self, "error_code", sanitized_error)
        object.__setattr__(
            self,
            "filters_sanitized",
            _validate_sanitized_filters(self.filters_sanitized),
        )
        if not isinstance(self.request_id, str):
            raise ValueError("SEMANTIC_SEARCH_REQUEST_ID_INVALID")
        if not self.request_id.strip() or len(self.request_id) > 128:
            raise ValueError("SEMANTIC_SEARCH_REQUEST_ID_INVALID")
        cleaned_request_id = _sanitize(self.request_id, 128)
        if not cleaned_request_id:
            raise ValueError("SEMANTIC_SEARCH_REQUEST_ID_INVALID")
        object.__setattr__(self, "request_id", cleaned_request_id)
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))


@dataclass(frozen=True, slots=True)
class HumanRetrievalEvaluation:
    id: uuid.UUID
    evaluation_run_id: uuid.UUID
    query_id: str
    result_document_id: uuid.UUID
    result_chunk_id: uuid.UUID
    evaluator_id: str
    usefulness_score: int
    legally_relevant: bool
    dataset_version: str
    embedding_model: str
    embedding_dimensions: int
    comments: str | None = None
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.query_id.strip() or not self.evaluator_id.strip():
            raise ValueError("HUMAN_EVALUATION_IDENTIFIERS_INVALID")
        if not 1 <= self.usefulness_score <= 5:
            raise ValueError("HUMAN_EVALUATION_SCORE_INVALID")
        if not self.dataset_version.strip() or not self.embedding_model.strip():
            raise ValueError("HUMAN_EVALUATION_METADATA_INVALID")
        if self.embedding_dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError("EMBEDDING_DIMENSIONS_MISMATCH")
        if self.comments is not None:
            cleaned = _sanitize(self.comments, 1000)
            object.__setattr__(self, "comments", cleaned or None)
        for field_name in ("evaluated_at", "created_at"):
            timestamp = getattr(self, field_name)
            if timestamp.tzinfo is None:
                object.__setattr__(self, field_name, timestamp.replace(tzinfo=UTC))
