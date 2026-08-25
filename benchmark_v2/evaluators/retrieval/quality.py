"""Quality checks for retrieved chunks, independent of production code."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._common import as_mapping, field, finite_number, identifier


@dataclass(frozen=True)
class ChunkQuality:
    chunk_id: str | None
    score: float
    valid: bool
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "score": self.score,
            "valid": self.valid,
            "issues": list(self.issues),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __float__(self) -> float:
        return self.score

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.score == float(other)
        if not isinstance(other, ChunkQuality):
            return NotImplemented
        return (
            self.chunk_id,
            self.score,
            self.valid,
            self.issues,
        ) == (other.chunk_id, other.score, other.valid, other.issues)


@dataclass(frozen=True)
class ChunkQualityReport:
    chunks: tuple[ChunkQuality, ...]
    mean_score: float | None
    valid_count: int
    total: int
    duplicate_ids: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        return "FULL" if self.valid_count == self.total else "PARTIAL"

    @property
    def invalid_count(self) -> int:
        return self.total - self.valid_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "mean_score": self.mean_score,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "total": self.total,
            "duplicate_ids": list(self.duplicate_ids),
            "status": self.status,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


def quality_score(
    chunk: Any,
    *,
    require_provenance: bool = True,
    min_text_chars: int = 1,
) -> ChunkQuality:
    """Score one chunk from traceability, content and ranking fields.

    The score is a diagnostic (not a relevance score): each of four checks
    contributes equally.  A missing field is reported explicitly so callers can
    distinguish poor quality from absent metadata.
    """

    item = as_mapping(chunk)
    chunk_id = identifier(item)
    issues: list[str] = []
    checks = 4
    if chunk_id is None:
        issues.append("missing_chunk_id")
    document_id = field(item, "document_id", "source_document_id", "doc_id")
    if document_id is None or not str(document_id).strip():
        issues.append("missing_document_id")
    content = field(item, "text", "content", "chunk_text", "body")
    if content is None or len(str(content).strip()) < min_text_chars:
        issues.append("missing_or_short_text")
    if require_provenance:
        provenance = field(item, "provenance", "source", "source_uri", "source_document_id", "corpus_id")
        if provenance is None or (isinstance(provenance, str) and not provenance.strip()):
            issues.append("missing_provenance")
    else:
        checks = 3
    score_value = field(item, "score", "similarity", "distance", default=None)
    if score_value is not None and not finite_number(score_value):
        issues.append("invalid_score")
    # Keep the score bounded and deterministic even when optional rank scores
    # are not supplied.  Invalid optional scores invalidate the chunk but do
    # not create an extra denominator component.
    passed = max(checks - min(len(issues), checks), 0)
    return ChunkQuality(chunk_id=chunk_id, score=passed / checks, valid=not issues, issues=tuple(issues))


def evaluate_chunk_quality(
    chunks: Sequence[Any],
    *,
    require_provenance: bool = True,
    min_text_chars: int = 1,
) -> ChunkQualityReport:
    """Evaluate all chunks and flag duplicate chunk identifiers."""

    evaluations: list[ChunkQuality] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for chunk in chunks:
        result = quality_score(chunk, require_provenance=require_provenance, min_text_chars=min_text_chars)
        if result.chunk_id is not None:
            if result.chunk_id in seen:
                duplicates.add(result.chunk_id)
            seen.add(result.chunk_id)
        evaluations.append(result)
    if duplicates:
        evaluations = [
            ChunkQuality(
                chunk_id=result.chunk_id,
                score=0.0 if result.chunk_id in duplicates else result.score,
                valid=False if result.chunk_id in duplicates else result.valid,
                issues=tuple(dict.fromkeys((*result.issues, "duplicate_chunk_id"))) if result.chunk_id in duplicates else result.issues,
            )
            for result in evaluations
        ]
    valid_count = sum(item.valid for item in evaluations)
    return ChunkQualityReport(
        chunks=tuple(evaluations),
        mean_score=sum(item.score for item in evaluations) / len(evaluations) if evaluations else None,
        valid_count=valid_count,
        total=len(evaluations),
        duplicate_ids=tuple(sorted(duplicates)),
    )


chunk_quality = evaluate_chunk_quality
chunk_quality_score = lambda chunk, **kwargs: quality_score(chunk, **kwargs).score
