"""FULL/PARTIAL comparison with explicit missing-query accounting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._common import RetrievalContractError, query_identifier, records
from .metrics import MetricSummary, evaluate_retrieval


class ComparisonError(ValueError):
    """Raised for an invalid run envelope or duplicate query identifiers."""


@dataclass(frozen=True)
class MetricComparison:
    full: float | None
    partial: float | None
    common: float | None
    delta: float | None
    full_evaluated: int
    partial_evaluated: int
    common_evaluated: int
    missing_in_partial: tuple[str, ...]
    missing_in_full: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "full": self.full,
            "partial": self.partial,
            "common": self.common,
            "delta": self.delta,
            "full_evaluated": self.full_evaluated,
            "partial_evaluated": self.partial_evaluated,
            "common_evaluated": self.common_evaluated,
            "missing_in_partial": list(self.missing_in_partial),
            "missing_in_full": list(self.missing_in_full),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


@dataclass(frozen=True)
class ComparisonReport:
    status: str
    full_status: str
    partial_status: str
    full_count: int
    partial_count: int
    compared_count: int
    missing_in_partial: tuple[str, ...]
    missing_in_full: tuple[str, ...]
    metrics: Mapping[str, MetricComparison]

    @property
    def coverage(self) -> float:
        return self.compared_count / self.full_count if self.full_count else 0.0

    @property
    def missing_count(self) -> int:
        return len(self.missing_in_partial) + len(self.missing_in_full)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "full_status": self.full_status,
            "partial_status": self.partial_status,
            "full_count": self.full_count,
            "partial_count": self.partial_count,
            "compared_count": self.compared_count,
            "coverage": self.coverage,
            "missing_count": self.missing_count,
            "missing_in_partial": list(self.missing_in_partial),
            "missing_in_full": list(self.missing_in_full),
            "metrics": {name: value.to_dict() for name, value in self.metrics.items()},
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


def _normalise_run(run: Any, label: str) -> tuple[list[Any], str, int | None]:
    if isinstance(run, Mapping):
        try:
            items = records(run)
        except RetrievalContractError as exc:
            raise ComparisonError(f"{label} has no records") from exc
        status = str(run.get("status", run.get("completeness", ""))).upper()
        expected = run.get("expected_count", run.get("expected_records", run.get("total_expected")))
    else:
        items = records(run)
        status = ""
        expected = None
    if status not in {"", "FULL", "PARTIAL"}:
        raise ComparisonError(f"{label}.status must be FULL or PARTIAL")
    if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int) or expected < 0):
        raise ComparisonError(f"{label}.expected_count must be a non-negative integer")
    if status == "FULL" and expected is not None and len(items) != expected:
        raise ComparisonError(f"{label} declares FULL with {len(items)} records; expected {expected}")
    seen: set[str] = set()
    for position, item in enumerate(items):
        item_id = query_identifier(item, position)
        if item_id in seen:
            raise ComparisonError(f"{label} contains duplicate query identifier {item_id!r}")
        seen.add(item_id)
    if not status:
        status = "FULL" if expected is not None and len(items) == expected else "PARTIAL"
    return items, status, expected


def _metric_value(summary: MetricSummary) -> float | None:
    return summary.value


def compare_full_partial(full: Any, partial: Any, ks: Sequence[int] = (3, 5)) -> ComparisonReport:
    """Compare two runs while retaining missing IDs and common-case metrics."""

    full_records, full_status, _ = _normalise_run(full, "full")
    partial_records, partial_status, _ = _normalise_run(partial, "partial")
    full_ids = [query_identifier(item, position) for position, item in enumerate(full_records)]
    partial_ids = [query_identifier(item, position) for position, item in enumerate(partial_records)]
    full_set, partial_set = set(full_ids), set(partial_ids)
    missing_in_partial = tuple(item for item in full_ids if item not in partial_set)
    missing_in_full = tuple(item for item in partial_ids if item not in full_set)
    common_ids = full_set & partial_set
    common_full = [item for item in full_records if query_identifier(item) in common_ids]
    common_partial = [item for item in partial_records if query_identifier(item) in common_ids]
    full_eval = evaluate_retrieval(full_records, ks)
    partial_eval = evaluate_retrieval(partial_records, ks)
    common_full_eval = evaluate_retrieval(common_full, ks)
    common_partial_eval = evaluate_retrieval(common_partial, ks)
    metrics: dict[str, MetricComparison] = {}
    names = tuple(full_eval.metrics.keys())
    for name in names:
        full_summary = full_eval.metrics[name]
        partial_summary = partial_eval.metrics[name]
        common_summary = common_full_eval.metrics[name]
        common_partial_summary = common_partial_eval.metrics[name]
        # The common metric is the partial-run value on common IDs when it is
        # defined; the full-run value is used as a fallback for records that
        # omit identical provider fields.  Missing values stay None.
        common_value = common_partial_summary.value
        if common_value is None and common_summary.value is not None:
            common_value = common_summary.value
        delta = None
        if full_summary.value is not None and partial_summary.value is not None:
            delta = partial_summary.value - full_summary.value
        metrics[name] = MetricComparison(
            full=_metric_value(full_summary),
            partial=_metric_value(partial_summary),
            common=common_value,
            delta=delta,
            full_evaluated=full_summary.evaluated,
            partial_evaluated=partial_summary.evaluated,
            common_evaluated=common_partial_summary.evaluated,
            missing_in_partial=tuple(dict.fromkeys((*missing_in_partial, *full_summary.missing_query_ids))),
            missing_in_full=tuple(dict.fromkeys((*missing_in_full, *partial_summary.missing_query_ids))),
        )
    status = "FULL" if full_status == "FULL" and partial_status == "FULL" and not missing_in_partial and not missing_in_full else "PARTIAL"
    return ComparisonReport(
        status=status,
        full_status=full_status,
        partial_status=partial_status,
        full_count=len(full_records),
        partial_count=len(partial_records),
        compared_count=len(common_ids),
        missing_in_partial=missing_in_partial,
        missing_in_full=missing_in_full,
        metrics=metrics,
    )


compare_runs = compare_full_partial
compare = compare_full_partial
