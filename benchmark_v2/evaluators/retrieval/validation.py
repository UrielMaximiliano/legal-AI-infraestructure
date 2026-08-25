"""Traceability, exclusion and leakage validation for retrieval outputs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from ._common import as_mapping, field, identifier, text


@dataclass(frozen=True)
class Violation:
    code: str
    item_id: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "item_id": self.item_id, "detail": self.detail}


@dataclass(frozen=True)
class ValidationReport:
    """A non-throwing validation result suitable for benchmark serialization."""

    passed: bool
    checked: int
    violations: tuple[Violation, ...] = ()
    status: str = "FULL"

    @property
    def ok(self) -> bool:
        return self.passed

    @property
    def valid(self) -> bool:
        return self.passed

    @property
    def leakage_count(self) -> int:
        return len(self.violations)

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "ok": self.passed,
            "valid": self.passed,
            "checked": self.checked,
            "violations": [violation.to_dict() for violation in self.violations],
            "violation_count": len(self.violations),
            "leakage_count": self.leakage_count,
            "status": self.status,
        }

    def __bool__(self) -> bool:
        return self.passed

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


def _items(value: Any) -> list[Any]:
    if isinstance(value, Mapping):
        for name in ("records", "results", "chunks", "retrieved", "candidates"):
            if name in value:
                value = value[name]
                break
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray)):
        return [value]
    return list(value)


def _set(values: Iterable[Any] | None) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, (str, bytes, bytearray)):
        return {str(values)}
    return {str(value) for value in values if value is not None and str(value).strip()}


def _content_hash(item: Any) -> str | None:
    raw = field(item, "content_hash", "text_sha256", "sha256", default=None)
    if raw is not None:
        return str(raw).lower()
    content = field(item, "text", "content", "chunk_text", "body", default=None)
    if content is None or not str(content).strip():
        return None
    return sha256(str(content).encode("utf-8")).hexdigest()


def validate_provenance(
    chunks: Sequence[Any],
    *,
    expected_corpus: str | None = None,
    expected_corpus_id: str | None = None,
    expected_source: str | None = None,
    required_fields: Sequence[str] = (),
    require_content_hash: bool = False,
    **_: Any,
) -> ValidationReport:
    """Validate that every result can be traced to a corpus document/chunk.

    Multiple field aliases are accepted because retrieval providers commonly
    call the same concepts ``doc_id``/``document_id`` and ``source``/``uri``.
    A supplied content hash is checked against the supplied content.
    """

    expected = expected_corpus_id or expected_corpus
    violations: list[Violation] = []
    items = _items(chunks)
    for position, chunk in enumerate(items):
        item = as_mapping(chunk) if not isinstance(chunk, (str, int)) else {}
        item_id = identifier(item) or f"item-{position}"
        chunk_id = identifier(item)
        document_id = field(item, "document_id", "source_document_id", "doc_id")
        provenance = field(
            item,
            "provenance",
            "source",
            "source_uri",
            "source_url",
            "source_type",
            "provenance_type",
            "uri",
            "corpus_id",
        )
        if chunk_id is None:
            violations.append(Violation("missing_chunk_id", item_id, "chunk identifier is required"))
        if document_id is None or not str(document_id).strip():
            violations.append(Violation("missing_document_id", item_id, "document identifier is required"))
        if provenance is None or (isinstance(provenance, str) and not provenance.strip()):
            violations.append(Violation("missing_provenance", item_id, "source/provenance is required"))
        corpus_id = field(item, "corpus_id", "corpus", "dataset", "dataset_id", "source_corpus_id")
        if expected is not None and corpus_id is not None and str(corpus_id) != str(expected):
            violations.append(Violation("unexpected_corpus", item_id, f"expected {expected!r}"))
        source = field(item, "source", "source_uri", "source_url", "uri", "source_id", default=None)
        if expected_source is not None and source is not None and str(source) != str(expected_source):
            violations.append(Violation("unexpected_source", item_id, f"expected {expected_source!r}"))
        for required in required_fields:
            value = field(item, required, default=None)
            if value is None or (isinstance(value, str) and not value.strip()):
                violations.append(Violation("missing_required_field", item_id, required))
        supplied_hash = field(item, "content_hash", "text_sha256", default=None)
        if require_content_hash and _content_hash(item) is None:
            violations.append(Violation("missing_content_hash", item_id, "content hash is required"))
        if supplied_hash is not None:
            content = field(item, "text", "content", "chunk_text", "body", default=None)
            if content is not None and str(supplied_hash).lower() != sha256(str(content).encode("utf-8")).hexdigest():
                violations.append(Violation("content_hash_mismatch", item_id, "content does not match content_hash"))
    return ValidationReport(not violations, len(items), tuple(violations), "FULL" if not violations else "PARTIAL")


def validate_corpus_exclusion(
    chunks: Sequence[Any],
    *,
    excluded_ids: Iterable[Any] | None = None,
    excluded_chunk_ids: Iterable[Any] | None = None,
    excluded_document_ids: Iterable[Any] | None = None,
    excluded_corpus_ids: Iterable[Any] | None = None,
    excluded_sources: Iterable[Any] | None = None,
    allowed_corpus_ids: Iterable[Any] | None = None,
    excluded_corpora: Iterable[Any] | None = None,
    **kwargs: Any,
) -> ValidationReport:
    """Ensure retrieved chunks do not come from an excluded corpus/split."""

    ids = _set(excluded_ids)
    chunk_ids = ids | _set(excluded_chunk_ids)
    document_ids = _set(excluded_document_ids)
    corpus_ids = _set(excluded_corpus_ids) | _set(excluded_corpora)
    sources = _set(excluded_sources)
    allowed = _set(allowed_corpus_ids)
    violations: list[Violation] = []
    items = _items(chunks)
    for position, chunk in enumerate(items):
        item = as_mapping(chunk) if not isinstance(chunk, (str, int)) else {}
        scalar_id = str(chunk) if isinstance(chunk, (str, int)) else None
        item_id = identifier(item) or scalar_id or f"item-{position}"
        chunk_id = identifier(item)
        if chunk_id is None:
            chunk_id = scalar_id
        document_id = field(item, "document_id", "source_document_id", "doc_id")
        corpus = field(item, "corpus_id", "corpus", "dataset", "dataset_id", "source_corpus_id")
        source = field(item, "source", "source_uri", "source_url", "provenance", "split")
        split = str(field(item, "split", "dataset_split", "partition", default="")).upper()
        explicit_excluded = field(item, "excluded", "is_excluded", "holdout", "is_holdout", default=False)
        if chunk_id in chunk_ids or document_id is not None and str(document_id) in document_ids:
            violations.append(Violation("excluded_identifier", item_id, "chunk/document is excluded"))
        if corpus is not None and str(corpus) in corpus_ids:
            violations.append(Violation("excluded_corpus", item_id, "corpus is excluded"))
        if source is not None and str(source) in sources:
            violations.append(Violation("excluded_source", item_id, "source is excluded"))
        if split in {"HOLDOUT", "HOLDOUT_10", "TEST", "EXCLUDED"} or bool(explicit_excluded):
            violations.append(Violation("excluded_split", item_id, "chunk is marked holdout/excluded"))
        if allowed and corpus is not None and str(corpus) not in allowed:
            violations.append(Violation("corpus_not_allowed", item_id, f"corpus {corpus!r} is not allowed"))
    return ValidationReport(not violations, len(items), tuple(violations), "FULL" if not violations else "PARTIAL")


def detect_leakage(
    chunks: Sequence[Any],
    *,
    queries: Sequence[Any] | None = None,
    indexed_chunks: Sequence[Any] | None = None,
    excluded_ids: Iterable[Any] | None = None,
    excluded_chunk_ids: Iterable[Any] | None = None,
    excluded_document_ids: Iterable[Any] | None = None,
    excluded_corpus_ids: Iterable[Any] | None = None,
    excluded_sources: Iterable[Any] | None = None,
    allowed_corpus_ids: Iterable[Any] | None = None,
    overlap_threshold: float = 1.0,
    **kwargs: Any,
) -> ValidationReport:
    """Detect explicit holdout leakage and exact query/index overlap.

    Lexical overlap is intentionally conservative: only exact normalized text,
    exact content hashes, or a caller-requested threshold of 1.0 is reported.
    Ordinary legal-language overlap is not leakage by itself.
    """

    base = validate_corpus_exclusion(
        chunks,
        excluded_ids=excluded_ids,
        excluded_chunk_ids=excluded_chunk_ids,
        excluded_document_ids=excluded_document_ids,
        excluded_corpus_ids=excluded_corpus_ids,
        excluded_sources=excluded_sources,
        allowed_corpus_ids=allowed_corpus_ids,
        **kwargs,
    )
    violations = list(base.violations)
    items = _items(chunks)
    query_items = _items(queries)
    index_items = _items(indexed_chunks)
    if not 0.0 < overlap_threshold <= 1.0:
        raise ValueError("overlap_threshold must be in (0, 1]")
    query_texts = {text(field(query, "query_text", "query", "text", "content", default=query)) for query in query_items}
    query_texts.discard("")
    query_hashes = {_content_hash(query) for query in query_items if _content_hash(query) is not None}
    indexed_hashes = {_content_hash(item) for item in index_items if _content_hash(item) is not None}
    for position, chunk in enumerate(items):
        item = as_mapping(chunk) if not isinstance(chunk, (str, int)) else {}
        scalar_id = str(chunk) if isinstance(chunk, (str, int)) else None
        item_id = identifier(item) or scalar_id or f"item-{position}"
        if bool(field(item, "leaked", "is_leaked", "leakage", default=False)):
            violations.append(Violation("explicit_leakage", item_id, "record is explicitly marked as leaked"))
        chunk_text = text(field(item, "text", "content", "chunk_text", "body", default=""))
        chunk_hash = _content_hash(item)
        if chunk_text and chunk_text in query_texts:
            violations.append(Violation("query_content_overlap", item_id, "chunk content equals query content"))
        if chunk_text and overlap_threshold < 1.0:
            chunk_tokens = set(chunk_text.split())
            for query_value in query_texts:
                query_tokens = set(query_value.split())
                if query_tokens and len(chunk_tokens & query_tokens) / len(query_tokens) >= overlap_threshold:
                    violations.append(Violation("query_content_overlap", item_id, "chunk content overlaps query"))
                    break
        if chunk_hash is not None and (chunk_hash in query_hashes or chunk_hash in indexed_hashes):
            violations.append(Violation("content_hash_overlap", item_id, "chunk content hash overlaps query/index"))
        query_id = field(item, "query_id", default=None)
        if query_id is not None and str(query_id) in {str(field(query, "query_id", "id", default="")) for query in query_items}:
            violations.append(Violation("query_identifier_overlap", item_id, "chunk carries a query identifier"))
    return ValidationReport(not violations, len(items), tuple(violations), "FULL" if not violations else "PARTIAL")


def validate_no_leakage(*args: Any, **kwargs: Any) -> ValidationReport:
    return detect_leakage(*args, **kwargs)


validate_leakage = detect_leakage
check_provenance = validate_provenance
check_corpus_exclusion = validate_corpus_exclusion
