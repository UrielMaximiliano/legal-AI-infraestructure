"""Deterministic retrieval quality metrics; informational by contract."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    query_id: str
    returned_ids: tuple[str, ...]
    relevant_ids: frozenset[str]
    latency_ms: float = 0.0
    usefulness_score: int | None = None
    legally_relevant: bool | None = None


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationReport:
    dataset_version: str
    query_count: int
    precision_at_3: float
    precision_at_5: float
    recall_at_3: float
    recall_at_5: float
    mrr: float
    usefulness_average: float | None
    legally_relevant_percent: float | None
    latency_p50_ms: float
    latency_p95_ms: float
    latency_max_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset_version": self.dataset_version,
            "query_count": self.query_count,
            "precision_at_3": self.precision_at_3,
            "precision_at_5": self.precision_at_5,
            "recall_at_3": self.recall_at_3,
            "recall_at_5": self.recall_at_5,
            "mrr": self.mrr,
            "usefulness_average": self.usefulness_average,
            "legally_relevant_percent": self.legally_relevant_percent,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_max_ms": self.latency_max_ms,
        }


def precision_at_k(
    returned_ids: Iterable[str],
    relevant_ids: frozenset[str],
    k: int,
) -> float:
    if k <= 0:
        raise ValueError("EVALUATION_K_INVALID")
    returned = tuple(returned_ids)[:k]
    return sum(item in relevant_ids for item in returned) / k


def recall_at_k(
    returned_ids: Iterable[str],
    relevant_ids: frozenset[str],
    k: int,
) -> float:
    if not relevant_ids:
        return 0.0
    returned = tuple(returned_ids)[:k]
    return sum(item in relevant_ids for item in returned) / len(relevant_ids)


def reciprocal_rank(returned_ids: Iterable[str], relevant_ids: frozenset[str]) -> float:
    for index, item in enumerate(returned_ids, start=1):
        if item in relevant_ids:
            return 1 / index
    return 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def evaluate_cases(
    cases: Iterable[EvaluationCase], *, dataset_version: str
) -> RetrievalEvaluationReport:
    values = tuple(cases)
    latencies = [float(case.latency_ms) for case in values]
    usefulness = [
        case.usefulness_score for case in values if case.usefulness_score is not None
    ]
    legal = [
        case.legally_relevant for case in values if case.legally_relevant is not None
    ]
    return RetrievalEvaluationReport(
        dataset_version=dataset_version,
        query_count=len(values),
        precision_at_3=(
            mean(precision_at_k(c.returned_ids, c.relevant_ids, 3) for c in values)
            if values
            else 0.0
        ),
        precision_at_5=(
            mean(precision_at_k(c.returned_ids, c.relevant_ids, 5) for c in values)
            if values
            else 0.0
        ),
        recall_at_3=(
            mean(recall_at_k(c.returned_ids, c.relevant_ids, 3) for c in values)
            if values
            else 0.0
        ),
        recall_at_5=(
            mean(recall_at_k(c.returned_ids, c.relevant_ids, 5) for c in values)
            if values
            else 0.0
        ),
        mrr=(
            mean(reciprocal_rank(c.returned_ids, c.relevant_ids) for c in values)
            if values
            else 0.0
        ),
        usefulness_average=(mean(usefulness) if usefulness else None),
        legally_relevant_percent=(
            100 * sum(bool(item) for item in legal) / len(legal) if legal else None
        ),
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p95_ms=_percentile(latencies, 0.95),
        latency_max_ms=max(latencies, default=0.0),
    )
