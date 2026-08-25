"""Information-retrieval metrics for benchmark-v2.

The functions in this module deliberately return ``None`` when a query has no
reference relevance labels.  A missing reference is not a failed retrieval and
must not silently become a zero in a benchmark report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import log2
from typing import Any

from ._common import RetrievalContractError, case_relevance, case_retrieved, query_identifier, ranked_ids, relevance_map


def _validate_k(k: int) -> int:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")
    return k


def recall_at_k(retrieved: Any, relevant: Any = None, k: int = 5) -> float | None:
    """Return binary Recall@k, or ``None`` when no relevance labels exist."""

    k = _validate_k(k)
    labels = relevance_map(relevant)
    if not labels:
        return None
    found = len(set(ranked_ids(retrieved)[:k]).intersection(labels))
    return found / len(labels)


def mean_recall_at_k(cases: Sequence[Any], k: int = 5) -> float | None:
    values = [recall_at_k(case_retrieved(case), case_relevance(case), k) for case in cases]
    observed = [value for value in values if value is not None]
    return sum(observed) / len(observed) if observed else None


def reciprocal_rank(retrieved: Any, relevant: Any = None, *, k: int | None = None) -> float | None:
    """Return the reciprocal rank of the first relevant result."""

    if k is not None:
        k = _validate_k(k)
    labels = relevance_map(relevant)
    if not labels:
        return None
    for rank, result_id in enumerate(ranked_ids(retrieved), start=1):
        if k is not None and rank > k:
            break
        if result_id in labels:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(cases: Sequence[Any]) -> float | None:
    values = [reciprocal_rank(case_retrieved(case), case_relevance(case)) for case in cases]
    observed = [value for value in values if value is not None]
    return sum(observed) / len(observed) if observed else None


def ndcg_at_k(retrieved: Any, relevance: Any = None, k: int = 5) -> float | None:
    """Return nDCG@k for binary or graded relevance labels."""

    k = _validate_k(k)
    labels = relevance_map(relevance)
    if not labels:
        return None
    gains = [labels.get(result_id, 0.0) for result_id in ranked_ids(retrieved)[:k]]
    dcg = sum(gain / log2(rank + 2) for rank, gain in enumerate(gains) if gain > 0)
    ideal = sorted(labels.values(), reverse=True)[:k]
    idcg = sum(gain / log2(rank + 2) for rank, gain in enumerate(ideal) if gain > 0)
    return dcg / idcg if idcg else None


def mean_ndcg_at_k(cases: Sequence[Any], k: int = 5) -> float | None:
    values = [ndcg_at_k(case_retrieved(case), case_relevance(case), k) for case in cases]
    observed = [value for value in values if value is not None]
    return sum(observed) / len(observed) if observed else None


@dataclass(frozen=True)
class MetricSummary:
    """An aggregate metric with explicit coverage and missing query IDs."""

    value: float | None
    evaluated: int
    total: int
    missing_query_ids: tuple[str, ...] = ()
    metric: str = "metric"

    @property
    def missing(self) -> int:
        return self.total - self.evaluated

    @property
    def status(self) -> str:
        return "FULL" if self.missing == 0 else "PARTIAL"

    @property
    def coverage(self) -> float:
        return self.evaluated / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "evaluated": self.evaluated,
            "total": self.total,
            "missing": self.missing,
            "missing_query_ids": list(self.missing_query_ids),
            "coverage": self.coverage,
            "status": self.status,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


@dataclass(frozen=True)
class RetrievalEvaluation:
    """Per-query records plus aggregate Recall/MRR/nDCG summaries."""

    records: tuple[dict[str, Any], ...]
    metrics: Mapping[str, MetricSummary]
    status: str
    total: int
    evaluated: int

    @property
    def missing(self) -> int:
        return self.total - self.evaluated

    @property
    def coverage(self) -> float:
        return self.evaluated / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [dict(record) for record in self.records],
            "metrics": {name: summary.to_dict() for name, summary in self.metrics.items()},
            "status": self.status,
            "total": self.total,
            "evaluated": self.evaluated,
            "missing": self.missing,
            "coverage": self.coverage,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


def _aggregate(values: list[float | None], ids: list[str], metric: str) -> MetricSummary:
    observed = [value for value in values if value is not None]
    missing = tuple(query_id for query_id, value in zip(ids, values) if value is None)
    return MetricSummary(
        value=sum(observed) / len(observed) if observed else None,
        evaluated=len(observed),
        total=len(values),
        missing_query_ids=missing,
        metric=metric,
    )


def evaluate_retrieval(cases: Sequence[Any], ks: Sequence[int] = (3, 5)) -> RetrievalEvaluation:
    """Evaluate a sequence of query cases and preserve per-query missingness."""

    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes, bytearray)):
        raise RetrievalContractError("cases must be a sequence")
    normalized_ks = tuple(dict.fromkeys(_validate_k(k) for k in ks))
    if not normalized_ks:
        raise ValueError("ks must contain at least one positive integer")
    records: list[dict[str, Any]] = []
    ids: list[str] = []
    metric_values: dict[str, list[float | None]] = {f"recall_at_{k}": [] for k in normalized_ks}
    metric_values["mrr"] = []
    metric_values.update({f"ndcg_at_{k}": [] for k in normalized_ks})
    for position, case in enumerate(cases):
        query_id = query_identifier(case, position)
        labels = case_relevance(case)
        retrieved = case_retrieved(case)
        record: dict[str, Any] = {"query_id": query_id}
        for k in normalized_ks:
            record[f"recall_at_{k}"] = recall_at_k(retrieved, labels, k)
            record[f"ndcg_at_{k}"] = ndcg_at_k(retrieved, labels, k)
            metric_values[f"recall_at_{k}"].append(record[f"recall_at_{k}"])
            metric_values[f"ndcg_at_{k}"].append(record[f"ndcg_at_{k}"])
        record["mrr"] = reciprocal_rank(retrieved, labels)
        metric_values["mrr"].append(record["mrr"])
        record["status"] = "FULL" if labels is not None and bool(relevance_map(labels)) else "PARTIAL"
        if record["status"] == "PARTIAL":
            record["missing_reason"] = "relevance_reference_missing"
        records.append(record)
        ids.append(query_id)
    summaries = {name: _aggregate(values, ids, name) for name, values in metric_values.items()}
    evaluated = max((summary.evaluated for summary in summaries.values()), default=0)
    return RetrievalEvaluation(
        records=tuple(records),
        metrics=summaries,
        status="FULL" if evaluated == len(records) else "PARTIAL",
        total=len(records),
        evaluated=evaluated,
    )


# Friendly aliases used by different benchmark callers.
mrr = reciprocal_rank
mrr_at_k = reciprocal_rank
ndcg = ndcg_at_k
evaluate = evaluate_retrieval
