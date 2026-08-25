"""Convenience case-level API around the retrieval metrics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .contract import CALCULATED, NOT_CALCULABLE, RetrievalCase, parse_case
from .metrics import evaluate_retrieval, ndcg_at_k, recall_at_k, reciprocal_rank


def evaluate_case(case: RetrievalCase | Mapping[str, Any], *, ks: Sequence[int] = (3, 5)) -> dict[str, Any]:
    """Return one auditable record; missing relevance is NOT_CALCULABLE."""

    try:
        parsed = parse_case(case)
    except (TypeError, ValueError) as exc:
        raw_id = case.get("query_id") if isinstance(case, Mapping) else None
        return {"query_id": raw_id, "status": NOT_CALCULABLE, "reason": str(exc)}
    labels = parsed.graded_relevance or parsed.relevant_ids
    record: dict[str, Any] = {"query_id": parsed.query_id, "status": CALCULATED}
    for k in ks:
        record[f"recall_at_{k}"] = recall_at_k(parsed.returned_ids, labels, k)
        record[f"ndcg_at_{k}"] = ndcg_at_k(parsed.returned_ids, labels, k)
    record["mrr"] = reciprocal_rank(parsed.returned_ids, labels)
    if not labels:
        record["status"] = NOT_CALCULABLE
        record["reason"] = "relevance_reference_missing"
    return record


def evaluate_cases(cases: Iterable[RetrievalCase | Mapping[str, Any]], *, ks: Sequence[int] = (3, 5)) -> list[dict[str, Any]]:
    return [evaluate_case(case, ks=ks) for case in cases]


class RetrievalEvaluator:
    """Reusable evaluator with both case-level and aggregate methods."""

    def __init__(self, *, ks: Sequence[int] = (3, 5)) -> None:
        self.ks = tuple(ks)

    def evaluate_case(self, case: RetrievalCase | Mapping[str, Any]) -> dict[str, Any]:
        return evaluate_case(case, ks=self.ks)

    def evaluate(self, cases: Sequence[RetrievalCase | Mapping[str, Any]]):
        return evaluate_retrieval(cases, self.ks)


evaluate_retrieval_case = evaluate_case
