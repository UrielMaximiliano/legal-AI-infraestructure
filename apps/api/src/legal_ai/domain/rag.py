"""Framework-independent domain rules for RAG generation."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ERROR_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,79}$")
_ALLOWED_ERRORS = frozenset(
    {
        "RAG_INVALID_REQUEST",
        "MISSING_REQUIRED_VARIABLES",
        "RAG_QUERY_EMPTY",
        "RAG_INSUFFICIENT_EVIDENCE",
        "RAG_OUTPUT_INVALID",
        "RAG_AUDIT_UNAVAILABLE",
        "SEMANTIC_SEARCH_AUDIT_UNAVAILABLE",
        "OLLAMA_UNAVAILABLE",
        "OLLAMA_TIMEOUT",
        "OLLAMA_AUTHENTICATION_FAILED",
        "OLLAMA_RESPONSE_INVALID",
        "RAG_IDEMPOTENCY_KEY_MISMATCH",
        "RAG_GENERATION_IN_PROGRESS",
        "RAG_GENERATION_CANCELLED",
        "RAG_GENERATION_INTERRUPTED",
    }
)

_EMBEDDING_CONTRACTS = {
    "legacy": (EMBEDDING_MODEL, EMBEDDING_DIMENSIONS),
    "imi_leg_06b": ("qwen3-embedding:0.6b", 1024),
}


class RagGenerationStatus(StrEnum):
    PENDING = "PENDING"
    RETRIEVING = "RETRIEVING"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RagSourceDisposition(StrEnum):
    SELECTED = "SELECTED"
    EXCLUDED_BUDGET = "EXCLUDED_BUDGET"
    EXCLUDED_DIVERSITY = "EXCLUDED_DIVERSITY"
    EXCLUDED_SCORE = "EXCLUDED_SCORE"


class RagEvaluationMode(StrEnum):
    FAKE = "FAKE"
    REAL = "REAL"
    HUMAN = "HUMAN"


def canonical_json(value: object) -> str:
    """Serialize JSON deterministically without exposing it in logs."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_hash(value: str, code: str = "RAG_HASH_INVALID") -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise ValueError(code)
    return value


def sanitize_error_code(value: object) -> str:
    if not isinstance(value, str):
        return "RAG_INTERNAL_ERROR"
    candidate = value.strip().upper()
    if candidate in _ALLOWED_ERRORS:
        return candidate
    if _ERROR_RE.fullmatch(candidate) and candidate.startswith("RAG_"):
        return candidate
    return "RAG_INTERNAL_ERROR"


def estimate_tokens(text: str) -> int:
    """Conservative, deterministic estimate used only for context budgeting."""

    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def citation_id(rank: int) -> str:
    if rank <= 0 or rank > 999:
        raise ValueError("RAG_CITATION_ID_INVALID")
    return f"SRC-{rank:03d}"


@dataclass(frozen=True, slots=True)
class RagRetrievedSource:
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    external_id: str
    title: str
    publication_date: str | None
    section_type: str
    generation: int
    similarity_score: float
    retrieval_rank: int
    citation_id: str
    excerpt: str
    article_number: str | None = None
    source_url: str | None = None
    disposition: RagSourceDisposition = RagSourceDisposition.SELECTED
    context_rank: int | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.external_id.strip() or not self.title.strip():
            raise ValueError("RAG_SOURCE_METADATA_INVALID")
        if not 0 <= self.similarity_score <= 1 or not math.isfinite(
            self.similarity_score
        ):
            raise ValueError("RAG_SOURCE_SCORE_INVALID")
        if self.retrieval_rank <= 0:
            raise ValueError("RAG_SOURCE_RANK_INVALID")
        if not re.fullmatch(r"SRC-[0-9]{3}", self.citation_id):
            raise ValueError("RAG_CITATION_ID_INVALID")
        if self.generation <= 0:
            raise ValueError("RAG_SOURCE_GENERATION_INVALID")
        if self.content_hash is not None:
            validate_hash(self.content_hash, "RAG_SOURCE_CONTENT_HASH_INVALID")
        if self.disposition is RagSourceDisposition.SELECTED:
            if self.context_rank is None or self.context_rank <= 0:
                raise ValueError("RAG_SOURCE_CONTEXT_RANK_REQUIRED")
        elif self.context_rank is not None:
            raise ValueError("RAG_SOURCE_CONTEXT_RANK_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class RagGenerationRun:
    id: uuid.UUID
    case_file_id: uuid.UUID
    template_id: uuid.UUID
    request_hash: str
    query_hash: str
    embedding_model: str = EMBEDDING_MODEL
    embedding_dimensions: int = EMBEDDING_DIMENSIONS
    profile_code: str = "legacy"
    generation_model: str = "qwen3.6:35b"
    prompt_version: str = "rag-legal-document-v1"
    schema_version: int = 1
    top_k: int = 8
    candidate_pool_size: int = 24
    minimum_score: float | None = 0.0
    idempotency_key_hash: str | None = None
    status: RagGenerationStatus = RagGenerationStatus.PENDING
    retrieved_count: int = 0
    selected_count: int = 0
    context_bytes: int = 0
    context_tokens_estimate: int = 0
    schema_repair_count: int = 0
    error_code: str | None = None
    request_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    draft_id: uuid.UUID | None = None
    context_hash: str | None = None
    prompt_hash: str | None = None
    generation_attempt_id: uuid.UUID | None = None
    retrieval_duration_ms: int | None = None
    generation_duration_ms: int | None = None
    validation_duration_ms: int | None = None
    total_duration_ms: int | None = None

    def __post_init__(self) -> None:
        validate_hash(self.request_hash, "RAG_REQUEST_HASH_INVALID")
        validate_hash(self.query_hash, "RAG_QUERY_HASH_INVALID")
        if self.idempotency_key_hash is not None:
            validate_hash(self.idempotency_key_hash, "RAG_IDEMPOTENCY_HASH_INVALID")
        expected = _EMBEDDING_CONTRACTS.get(self.profile_code)
        if expected is None:
            raise ValueError("RAG_PROFILE_INVALID")
        if self.embedding_model != expected[0]:
            raise ValueError("RAG_EMBEDDING_MODEL_INVALID")
        if self.embedding_dimensions != expected[1]:
            raise ValueError("RAG_EMBEDDING_DIMENSIONS_INVALID")
        if self.generation_model != "qwen3.6:35b":
            raise ValueError("RAG_GENERATION_MODEL_INVALID")
        if (
            not 3 <= self.top_k <= 20
            or not self.top_k <= self.candidate_pool_size <= 50
        ):
            raise ValueError("RAG_RETRIEVAL_LIMIT_INVALID")
        if self.minimum_score is not None and not 0 <= self.minimum_score <= 1:
            raise ValueError("RAG_SCORE_INVALID")
        if (
            self.retrieved_count < 0
            or not 0 <= self.selected_count <= self.retrieved_count
        ):
            raise ValueError("RAG_SOURCE_COUNT_INVALID")
        if self.schema_repair_count not in {0, 1}:
            raise ValueError("RAG_SCHEMA_REPAIR_COUNT_INVALID")
        if self.error_code is not None:
            sanitize_error_code(self.error_code)

    def transition(
        self, status: RagGenerationStatus, *, now: datetime | None = None
    ) -> RagGenerationRun:
        allowed = {
            RagGenerationStatus.PENDING: {
                RagGenerationStatus.RETRIEVING,
                RagGenerationStatus.FAILED,
                RagGenerationStatus.CANCELLED,
            },
            RagGenerationStatus.RETRIEVING: {
                RagGenerationStatus.GENERATING,
                RagGenerationStatus.FAILED,
                RagGenerationStatus.CANCELLED,
            },
            RagGenerationStatus.GENERATING: {
                RagGenerationStatus.VALIDATING,
                RagGenerationStatus.FAILED,
                RagGenerationStatus.CANCELLED,
            },
            RagGenerationStatus.VALIDATING: {
                RagGenerationStatus.SUCCEEDED,
                RagGenerationStatus.FAILED,
                RagGenerationStatus.CANCELLED,
            },
            RagGenerationStatus.SUCCEEDED: set(),
            RagGenerationStatus.FAILED: set(),
            RagGenerationStatus.CANCELLED: set(),
        }
        if status not in allowed[self.status]:
            raise ValueError("RAG_INVALID_STATE_TRANSITION")
        timestamp = now or datetime.now(UTC)
        terminal = status in {
            RagGenerationStatus.SUCCEEDED,
            RagGenerationStatus.FAILED,
            RagGenerationStatus.CANCELLED,
        }
        return replace(
            self,
            status=status,
            updated_at=timestamp,
            finished_at=timestamp if terminal else None,
        )
