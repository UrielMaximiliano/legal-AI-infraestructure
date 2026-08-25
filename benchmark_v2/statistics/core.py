"""Reproducible, case-level statistics for Benchmark v2.

The functions in this module deliberately operate on the case as the unit of
analysis.  In particular, :func:`paired_bootstrap` resamples case indices once
and applies the same indices to both systems; independently bootstrapping the
two systems would destroy the design of the benchmark.

Only the Python standard library is required.  A percentile interval is always
available.  BCa is used when the jackknife acceleration is identifiable; for a
degenerate or one-case sample the result records an explicit fallback to the
percentile interval instead of silently pretending that BCa was computed.

The returned dictionaries are intentionally JSON-friendly and contain the
method, seed, number of resamples, and unit of resampling.  This makes the
statistical output auditable without serialising the complete bootstrap
distribution by default.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from itertools import product
from math import comb, isfinite, sqrt
from numbers import Integral, Real
from statistics import NormalDist, fmean, median, pstdev
from typing import Any, TypeAlias

Statistic: TypeAlias = str | Callable[[Sequence[float]], float]
DEFAULT_RESAMPLES = 10_000
DEFAULT_CONFIDENCE_LEVEL = 0.95
_IDENTIFIER_KEYS = ("case_id", "record_id", "id")
_RECORD_KEYS = ("records", "results", "rows", "cases")
_NON_METRIC_KEYS = frozenset(
    {
        "case_id",
        "record_id",
        "id",
        "run_id",
        "status",
        "completeness",
        "dimensions",
        "metadata",
        "expected_count",
        "error",
        "error_code",
    }
)


def _validate_seed(seed: int) -> int:
    if not isinstance(seed, Integral) or isinstance(seed, bool):
        raise TypeError("seed must be an explicit integer")
    return int(seed)


def _validate_resamples(n_resamples: int) -> int:
    if not isinstance(n_resamples, Integral) or isinstance(n_resamples, bool):
        raise TypeError("n_resamples must be an integer")
    if n_resamples < 1:
        raise ValueError("n_resamples must be positive")
    return int(n_resamples)


def _validate_confidence(confidence_level: float) -> float:
    if isinstance(confidence_level, bool) or not isinstance(confidence_level, Real):
        raise TypeError("confidence_level must be a number")
    confidence = float(confidence_level)
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")
    return confidence


def _finite_number(value: Any, label: str = "score") -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{label} must be a finite number")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _values(values: Iterable[Any], *, label: str = "scores") -> list[float]:
    result = [
        _finite_number(value, f"{label}[{index}]") for index, value in enumerate(values)
    ]
    if not result:
        raise ValueError(f"{label} must contain at least one score")
    return result


def _statistic_function(
    statistic: Statistic,
) -> tuple[str, Callable[[Sequence[float]], float]]:
    if isinstance(statistic, str):
        name = statistic.lower().strip()
        if name == "mean":
            return name, lambda sample: fmean(sample)
        if name == "median":
            return name, lambda sample: float(median(sample))
        raise ValueError("statistic must be 'mean', 'median', or a callable")
    if not callable(statistic):
        raise TypeError("statistic must be 'mean', 'median', or a callable")

    def apply(sample: Sequence[float]) -> float:
        return _finite_number(statistic(sample), "statistic result")

    return getattr(statistic, "__name__", "custom"), apply


def _percentile(values: Sequence[float], quantile: float) -> float:
    """Linear-interpolated percentile with a deterministic standard definition."""

    if not values:
        raise ValueError("cannot calculate a percentile of an empty sample")
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _normal_interval(
    estimate: float, values: Sequence[float], confidence_level: float
) -> tuple[float, float]:
    if len(values) < 2:
        return estimate, estimate
    standard_error = pstdev(values) / sqrt(len(values))
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
    return estimate - z * standard_error, estimate + z * standard_error


def _bootstrap_samples(
    values: Sequence[float],
    *,
    statistic: Callable[[Sequence[float]], float],
    n_resamples: int,
    seed: int,
) -> list[float]:
    # Import locally so importing the package never touches global RNG state.
    import random

    rng = random.Random(_validate_seed(seed))
    size = len(values)
    distribution: list[float] = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(size)] for _ in range(size)]
        distribution.append(_finite_number(statistic(sample), "bootstrap statistic"))
    return distribution


def _bca_interval(
    observed: float,
    distribution: Sequence[float],
    values: Sequence[float],
    *,
    statistic: Callable[[Sequence[float]], float],
    confidence_level: float,
) -> tuple[float, float] | None:
    """Return a BCa interval or ``None`` when its corrections are not defined."""

    if len(values) < 2 or not distribution:
        return None
    less = sum(value < observed for value in distribution)
    equal = sum(value == observed for value in distribution)
    # Mid-rank ties avoid infinite z0 values for a bootstrap distribution that
    # is discrete, which is common for benchmark scores.
    probability = (less + 0.5 * equal) / len(distribution)
    epsilon = 1.0 / (2.0 * (len(distribution) + 1.0))
    probability = min(1.0 - epsilon, max(epsilon, probability))
    z0 = NormalDist().inv_cdf(probability)

    jackknife = [
        _finite_number(
            statistic(values[:index] + values[index + 1 :]), "jackknife statistic"
        )
        for index in range(len(values))
    ]
    jack_mean = fmean(jackknife)
    centered = [jack_mean - value for value in jackknife]
    denominator = 6.0 * sum(value * value for value in centered) ** 1.5
    if denominator == 0.0 or not isfinite(denominator):
        return None
    acceleration = sum(value**3 for value in centered) / denominator
    alpha = (1.0 - confidence_level) / 2.0

    def adjusted_quantile(raw_alpha: float) -> float | None:
        z_alpha = NormalDist().inv_cdf(raw_alpha)
        denominator_inner = 1.0 - acceleration * (z0 + z_alpha)
        if denominator_inner == 0.0:
            return None
        adjusted = NormalDist().cdf(z0 + (z0 + z_alpha) / denominator_inner)
        if not isfinite(adjusted):
            return None
        return min(1.0, max(0.0, adjusted))

    low_q = adjusted_quantile(alpha)
    high_q = adjusted_quantile(1.0 - alpha)
    if low_q is None or high_q is None or low_q > high_q:
        return None
    return _percentile(distribution, low_q), _percentile(distribution, high_q)


def _interval_result(
    *,
    estimate: float,
    distribution: Sequence[float],
    values: Sequence[float],
    statistic_name: str,
    statistic_function: Callable[[Sequence[float]], float],
    confidence_level: float,
    requested_method: str,
    seed: int,
    n_resamples: int,
) -> dict[str, Any]:
    method = requested_method.lower().strip()
    if method not in {"percentile", "bca"}:
        raise ValueError("method must be 'percentile' or 'bca'")
    alpha = (1.0 - confidence_level) / 2.0
    low = _percentile(distribution, alpha)
    high = _percentile(distribution, 1.0 - alpha)
    used_method = "percentile"
    fallback_reason: str | None = None
    if method == "bca":
        bca = _bca_interval(
            estimate,
            distribution,
            values,
            statistic=statistic_function,
            confidence_level=confidence_level,
        )
        if bca is not None:
            low, high = bca
            used_method = "bca"
        else:
            fallback_reason = (
                "BCa no identificable: muestra degenerada o aceleración jackknife nula"
            )
    return {
        "estimate": estimate,
        "ci_low": low,
        "ci_high": high,
        "low": low,
        "high": high,
        "confidence_level": confidence_level,
        "alpha": 1.0 - confidence_level,
        "method": used_method,
        "interval_method": used_method,
        "requested_method": method,
        "fallback_reason": fallback_reason,
        "statistic": statistic_name,
        "n": len(values),
        "n_resamples": n_resamples,
        "seed": seed,
        "resampling_unit": "case",
    }


def bootstrap_ci(
    values: Iterable[Any],
    *,
    seed: int,
    statistic: Statistic = "mean",
    n_resamples: int = DEFAULT_RESAMPLES,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    method: str = "bca",
    return_distribution: bool = False,
) -> dict[str, Any]:
    """Calculate a deterministic one-sample bootstrap interval.

    ``seed`` is intentionally required.  If ``method='bca'`` is not viable,
    ``method`` in the result is ``'percentile'`` and ``fallback_reason`` says
    why; this is part of the result contract.
    """

    clean = _values(values)
    seed_value = _validate_seed(seed)
    resamples = _validate_resamples(n_resamples)
    confidence = _validate_confidence(confidence_level)
    statistic_name, statistic_function = _statistic_function(statistic)
    estimate = _finite_number(statistic_function(clean), "estimate")
    distribution = _bootstrap_samples(
        clean,
        statistic=statistic_function,
        n_resamples=resamples,
        seed=seed_value,
    )
    result = _interval_result(
        estimate=estimate,
        distribution=distribution,
        values=clean,
        statistic_name=statistic_name,
        statistic_function=statistic_function,
        confidence_level=confidence,
        requested_method=method,
        seed=seed_value,
        n_resamples=resamples,
    )
    if return_distribution:
        result["bootstrap_distribution"] = list(distribution)
    return result


def summarize(
    values: Iterable[Any],
    *,
    seed: int | None = None,
    n_resamples: int = DEFAULT_RESAMPLES,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    interval_method: str = "analytic",
    metric: str | None = None,
) -> dict[str, Any]:
    """Return mean, median, dispersion, and explicit intervals for one metric.

    The default mean interval is a deterministic normal approximation.  Pass
    ``interval_method='bootstrap'`` plus an explicit ``seed`` to obtain BCa
    (with documented percentile fallback) intervals for both mean and median.
    Analytic median intervals are not asserted because they require a
    distributional assumption, so ``median_ci`` is ``None`` in that mode.
    """

    clean = _values(values)
    confidence = _validate_confidence(confidence_level)
    average = fmean(clean)
    middle = float(median(clean))
    deviation = pstdev(clean) if len(clean) > 1 else 0.0
    method = interval_method.lower().strip()
    if method not in {"analytic", "bootstrap"}:
        raise ValueError("interval_method must be 'analytic' or 'bootstrap'")

    if method == "bootstrap":
        if seed is None:
            raise ValueError("seed is required when interval_method='bootstrap'")
        seed_value = _validate_seed(seed)
        mean_ci = bootstrap_ci(
            clean,
            seed=seed_value,
            statistic="mean",
            n_resamples=n_resamples,
            confidence_level=confidence,
            method="bca",
        )
        median_ci = bootstrap_ci(
            clean,
            seed=seed_value + 1,
            statistic="median",
            n_resamples=n_resamples,
            confidence_level=confidence,
            method="bca",
        )
        effective_seed: int | None = seed_value
    else:
        low, high = _normal_interval(average, clean, confidence)
        mean_ci = {
            "estimate": average,
            "ci_low": low,
            "ci_high": high,
            "low": low,
            "high": high,
            "confidence_level": confidence,
            "method": "normal",
            "interval_method": "analytic",
            "requested_method": "analytic",
            "fallback_reason": None,
            "statistic": "mean",
            "n": len(clean),
            "n_resamples": 0,
            "seed": None,
            "resampling_unit": "case",
        }
        median_ci = None
        effective_seed = None if seed is None else _validate_seed(seed)

    result: dict[str, Any] = {
        "metric": metric,
        "n": len(clean),
        "mean": average,
        "median": middle,
        "sd": deviation,
        "min": min(clean),
        "max": max(clean),
        "mean_ci": mean_ci,
        "median_ci": median_ci,
        "mean_ci_low": mean_ci["ci_low"],
        "mean_ci_high": mean_ci["ci_high"],
        "median_ci_low": None if median_ci is None else median_ci["ci_low"],
        "median_ci_high": None if median_ci is None else median_ci["ci_high"],
        # ci_low/high are retained as convenient aliases for the primary mean.
        "ci_low": mean_ci["ci_low"],
        "ci_high": mean_ci["ci_high"],
        "confidence_level": confidence,
        "interval_method": method,
        "seed": effective_seed,
        "resampling_unit": "case",
    }
    return result


def _records(
    data: Any,
) -> tuple[list[Mapping[str, Any]], str | None, str | None, int | None]:
    """Normalise a run envelope or a sequence of case records."""

    if isinstance(data, Mapping):
        raw_records = next((data[key] for key in _RECORD_KEYS if key in data), None)
        if raw_records is None:
            return (
                [data],
                data.get("status"),
                data.get("run_id"),
                data.get("expected_count"),
            )
        if not isinstance(raw_records, Sequence) or isinstance(
            raw_records, (str, bytes, bytearray)
        ):
            raise TypeError("records/results/rows/cases must be a sequence")
        records = []
        for index, record in enumerate(raw_records):
            if not isinstance(record, Mapping):
                raise TypeError(f"record {index} must be a mapping")
            records.append(record)
        return (
            records,
            data.get("status"),
            data.get("run_id"),
            data.get("expected_count"),
        )
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        records = []
        for index, record in enumerate(data):
            if not isinstance(record, Mapping):
                raise TypeError(f"record {index} must be a mapping")
            records.append(record)
        return records, None, None, None
    raise TypeError("run data must be an envelope or a sequence of mappings")


def _infer_metrics(records: Sequence[Mapping[str, Any]]) -> list[str]:
    names: set[str] = set()
    for record in records:
        for key, value in record.items():
            if key in _NON_METRIC_KEYS or key.startswith("_"):
                continue
            if (
                isinstance(value, Real)
                and not isinstance(value, bool)
                and isfinite(float(value))
            ):
                names.add(str(key))
    return sorted(names)


def _metric_values(
    records: Sequence[Mapping[str, Any]], metric: str
) -> tuple[list[float], int]:
    values: list[float] = []
    missing = 0
    for index, record in enumerate(records):
        if metric not in record or record[metric] is None:
            missing += 1
            continue
        values.append(_finite_number(record[metric], f"record {index}.{metric}"))
    if not values:
        raise ValueError(f"metric {metric!r} has no finite case values")
    return values, missing


def case_statistics(
    data: Any,
    *,
    metrics: Iterable[str] | None = None,
    seed: int | None = None,
    n_resamples: int = DEFAULT_RESAMPLES,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    interval_method: str = "analytic",
) -> list[dict[str, Any]]:
    """Summarise each metric independently, retaining case coverage metadata."""

    records, status, run_id, expected_count = _records(data)
    names = (
        [str(metric) for metric in metrics]
        if metrics is not None
        else _infer_metrics(records)
    )
    if not names:
        raise ValueError("at least one numeric metric is required")
    rows: list[dict[str, Any]] = []
    for offset, metric in enumerate(names):
        if metric.lower() in {"overall", "overall_score", "composite_score"}:
            raise ValueError("opaque overall scores are not valid table metrics")
        values, missing = _metric_values(records, metric)
        metric_seed = None if seed is None else _validate_seed(seed) + offset
        summary = summarize(
            values,
            seed=metric_seed,
            n_resamples=n_resamples,
            confidence_level=confidence_level,
            interval_method=interval_method,
            metric=metric,
        )
        summary.update(
            {
                "run_id": run_id,
                "status": status,
                "case_count": len(records),
                "observed_case_count": len(values),
                "missing_case_count": missing,
                "expected_count": expected_count,
                "coverage": None
                if expected_count is None
                else len(records) / expected_count
                if expected_count
                else 1.0,
            }
        )
        rows.append(summary)
    return rows


def per_case_table(
    data: Any, *, metrics: Iterable[str] | None = None
) -> list[dict[str, Any]]:
    """Return an auditable table of case-level values, without a composite score."""

    records, status, run_id, _ = _records(data)
    names = (
        [str(metric) for metric in metrics]
        if metrics is not None
        else _infer_metrics(records)
    )
    for metric in names:
        if metric.lower() in {"overall", "overall_score", "composite_score"}:
            raise ValueError("opaque overall scores are not valid table metrics")
    output: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        case_id = next(
            (record[key] for key in _IDENTIFIER_KEYS if key in record), index
        )
        row: dict[str, Any] = {"run_id": run_id, "status": status, "case_id": case_id}
        for metric in names:
            value = record.get(metric)
            row[metric] = (
                None
                if value is None
                else _finite_number(value, f"case {case_id}.{metric}")
            )
        output.append(row)
    return output


def _case_id(record: Mapping[str, Any], fallback: int) -> Any:
    for key in _IDENTIFIER_KEYS:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return fallback


def _aligned_values(
    left: Any,
    right: Any,
    metric: str,
) -> tuple[list[float], list[float], dict[str, Any]]:
    left_records, left_status, left_run_id, left_expected = _records(left)
    right_records, right_status, right_run_id, right_expected = _records(right)
    left_has_ids = any(
        any(key in row for key in _IDENTIFIER_KEYS) for row in left_records
    )
    right_has_ids = any(
        any(key in row for key in _IDENTIFIER_KEYS) for row in right_records
    )
    if left_has_ids != right_has_ids:
        raise ValueError(
            "paired runs must both provide case identifiers or both use positional records"
        )

    if left_has_ids:
        left_map: dict[Any, Mapping[str, Any]] = {}
        right_map: dict[Any, Mapping[str, Any]] = {}
        for index, row in enumerate(left_records):
            key = _case_id(row, index)
            if key in left_map:
                raise ValueError(f"duplicate case identifier in left run: {key!r}")
            left_map[key] = row
        for index, row in enumerate(right_records):
            key = _case_id(row, index)
            if key in right_map:
                raise ValueError(f"duplicate case identifier in right run: {key!r}")
            right_map[key] = row
        shared = [key for key in left_map if key in right_map]
        if not shared:
            raise ValueError("paired runs have no shared case identifiers")
        left_values = [
            _finite_number(left_map[key].get(metric), f"case {key}.{metric}")
            for key in shared
        ]
        right_values = [
            _finite_number(right_map[key].get(metric), f"case {key}.{metric}")
            for key in shared
        ]
    else:
        if len(left_records) != len(right_records):
            raise ValueError("positional paired runs must have equal lengths")
        shared = list(range(len(left_records)))
        if not shared:
            raise ValueError("paired runs must contain at least one case")
        left_values = [
            _finite_number(row.get(metric), f"case {key}.{metric}")
            for key, row in zip(shared, left_records)
        ]
        right_values = [
            _finite_number(row.get(metric), f"case {key}.{metric}")
            for key, row in zip(shared, right_records)
        ]
    return (
        left_values,
        right_values,
        {
            "paired_case_ids": shared,
            "paired_case_count": len(shared),
            "left_case_count": len(left_records),
            "right_case_count": len(right_records),
            "left_status": left_status,
            "right_status": right_status,
            "left_run_id": left_run_id,
            "right_run_id": right_run_id,
            "left_expected_count": left_expected,
            "right_expected_count": right_expected,
            "left_excluded_case_count": len(left_records) - len(shared),
            "right_excluded_case_count": len(right_records) - len(shared),
        },
    )


def _two_sided_bootstrap_p(
    distribution: Sequence[float], null_value: float = 0.0
) -> float:
    """P-value convention: plus-one corrected two-sided bootstrap tail at zero."""

    if not distribution:
        return 1.0
    lower = (sum(value <= null_value for value in distribution) + 1.0) / (
        len(distribution) + 1.0
    )
    upper = (sum(value >= null_value for value in distribution) + 1.0) / (
        len(distribution) + 1.0
    )
    return min(1.0, 2.0 * min(lower, upper))


def paired_bootstrap(
    left: Iterable[Any],
    right: Iterable[Any] | None = None,
    *,
    seed: int,
    statistic: Statistic = "mean",
    n_resamples: int = DEFAULT_RESAMPLES,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    method: str = "bca",
    return_distribution: bool = False,
) -> dict[str, Any]:
    """Bootstrap a paired delta while preserving each case's pair.

    If ``right`` is omitted, ``left`` is interpreted as the already computed
    per-case differences.  The primary form accepts both systems and samples
    one common set of indices for every bootstrap replicate.
    """

    left_values = _values(left, label="left")
    if right is None:
        differences = left_values
        right_values = None
    else:
        right_values = _values(right, label="right")
        if len(left_values) != len(right_values):
            raise ValueError("paired samples must have equal lengths")
        differences = [
            left_value - right_value
            for left_value, right_value in zip(left_values, right_values)
        ]
    seed_value = _validate_seed(seed)
    resamples = _validate_resamples(n_resamples)
    confidence = _validate_confidence(confidence_level)
    statistic_name, statistic_function = _statistic_function(statistic)
    estimate = _finite_number(statistic_function(differences), "paired delta")
    distribution = _bootstrap_samples(
        differences,
        statistic=statistic_function,
        n_resamples=resamples,
        seed=seed_value,
    )
    interval = _interval_result(
        estimate=estimate,
        distribution=distribution,
        values=differences,
        statistic_name=statistic_name,
        statistic_function=statistic_function,
        confidence_level=confidence,
        requested_method=method,
        seed=seed_value,
        n_resamples=resamples,
    )
    result: dict[str, Any] = {
        **interval,
        "delta": estimate,
        "mean_delta": fmean(differences),
        "median_delta": float(median(differences)),
        "p_value": _two_sided_bootstrap_p(distribution),
        "p_value_method": "two-sided bootstrap tail at zero with plus-one correction",
        "n": len(differences),
        "wins": sum(value > 0.0 for value in differences),
        "losses": sum(value < 0.0 for value in differences),
        "ties": sum(value == 0.0 for value in differences),
        "effect_size": fmean(differences) / pstdev(differences)
        if pstdev(differences)
        else None,
        "paired": right_values is not None,
        "resampling_unit": "case",
    }
    if return_distribution:
        result["bootstrap_distribution"] = list(distribution)
    return result


def _rank_abs(values: Sequence[float]) -> list[float]:
    ordered = sorted(
        (abs(value), index) for index, value in enumerate(values) if value != 0.0
    )
    ranks = [0.0] * len(values)
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][0] == ordered[position][0]:
            end += 1
        rank = (position + 1 + end) / 2.0
        for _, index in ordered[position:end]:
            ranks[index] = rank
        position = end
    return ranks


def _sign_test_p(values: Sequence[float]) -> float:
    nonzero = [value for value in values if value != 0.0]
    if not nonzero:
        return 1.0
    negatives = sum(value < 0.0 for value in nonzero)
    n = len(nonzero)
    tail = sum(comb(n, index) for index in range(min(negatives, n - negatives) + 1)) / (
        2.0**n
    )
    return min(1.0, 2.0 * tail)


def _wilcoxon(values: Sequence[float]) -> dict[str, Any]:
    nonzero = [value for value in values if value != 0.0]
    n = len(nonzero)
    if not nonzero:
        return {
            "test": "wilcoxon_signed_rank",
            "n_nonzero": 0,
            "statistic": 0.0,
            "w_plus": 0.0,
            "w_minus": 0.0,
            "p_value": 1.0,
            "method": "degenerate_all_ties",
        }
    ranks = _rank_abs(nonzero)
    w_plus = sum(rank for rank, value in zip(ranks, nonzero) if value > 0.0)
    w_minus = sum(rank for rank, value in zip(ranks, nonzero) if value < 0.0)
    statistic = min(w_plus, w_minus)
    abs_values = sorted(abs(value) for value in nonzero)
    has_ties = any(
        abs_values[index] == abs_values[index - 1]
        for index in range(1, len(abs_values))
    )
    if n <= 20 and not has_ties:
        total = 0
        for signs in product((-1, 1), repeat=n):
            w_pos = sum(rank for rank, sign in zip(ranks, signs) if sign > 0)
            if min(w_pos, sum(ranks) - w_pos) <= statistic + 1e-12:
                total += 1
        p_value = total / (2.0**n)
        method = "exact_no_ties"
    else:
        tie_counts: list[int] = []
        position = 0
        while position < n:
            end = position + 1
            while end < n and abs_values[end] == abs_values[position]:
                end += 1
            tie_counts.append(end - position)
            position = end
        variance = (
            n * (n + 1) * (2 * n + 1) - sum(count**3 - count for count in tie_counts)
        ) / 24.0
        mean_rank = n * (n + 1) / 4.0
        if variance <= 0.0:
            p_value = 1.0
        else:
            continuity = (
                0.5 if w_plus > mean_rank else -0.5 if w_plus < mean_rank else 0.0
            )
            z_value = (w_plus - mean_rank - continuity) / sqrt(variance)
            p_value = min(1.0, 2.0 * NormalDist().cdf(-abs(z_value)))
        method = "normal_tie_corrected_continuity"
    return {
        "test": "wilcoxon_signed_rank",
        "n_nonzero": n,
        "statistic": statistic,
        "w_plus": w_plus,
        "w_minus": w_minus,
        "p_value": p_value,
        "method": method,
    }


def sensitivity_tests(
    left: Iterable[Any],
    right: Iterable[Any] | None = None,
    *,
    seed: int,
    statistic: Statistic = "mean",
    n_resamples: int = DEFAULT_RESAMPLES,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    method: str = "bca",
    trim_fraction: float = 0.10,
) -> dict[str, Any]:
    """Run robust sensitivity checks for a paired comparison.

    The primary result is the paired bootstrap.  The sign test, Wilcoxon
    signed-rank test, trimmed mean, and leave-one-case-out range are diagnostics
    rather than hidden decision rules; each is returned separately.
    """

    left_values = _values(left, label="left")
    if right is None:
        differences = left_values
    else:
        right_values = _values(right, label="right")
        if len(left_values) != len(right_values):
            raise ValueError("paired samples must have equal lengths")
        differences = [
            left_value - right_value
            for left_value, right_value in zip(left_values, right_values)
        ]
    if isinstance(trim_fraction, bool) or not isinstance(trim_fraction, Real):
        raise TypeError("trim_fraction must be a number")
    trim = float(trim_fraction)
    if not 0.0 <= trim < 0.5:
        raise ValueError("trim_fraction must be between 0 and 0.5")
    primary = paired_bootstrap(
        differences,
        seed=seed,
        statistic=statistic,
        n_resamples=n_resamples,
        confidence_level=confidence_level,
        method=method,
    )
    ordered = sorted(differences)
    trim_count = int(len(ordered) * trim)
    retained = ordered[trim_count : len(ordered) - trim_count] or ordered
    loo = [
        fmean(differences[:index] + differences[index + 1 :])
        for index in range(len(differences))
        if len(differences) > 1
    ]
    result = {
        "primary": primary,
        "delta": primary["delta"],
        "mean_delta": fmean(differences),
        "median_delta": float(median(differences)),
        "trimmed_mean_delta": fmean(retained),
        "trim_fraction": trim,
        "sign_test": {
            "test": "paired_sign_test",
            "n_nonzero": sum(value != 0.0 for value in differences),
            "p_value": _sign_test_p(differences),
        },
        "wilcoxon": _wilcoxon(differences),
        "leave_one_case_out": {
            "n": len(loo),
            "min": min(loo) if loo else fmean(differences),
            "max": max(loo) if loo else fmean(differences),
            "range": (min(loo), max(loo))
            if loo
            else (fmean(differences), fmean(differences)),
        },
        "seed": _validate_seed(seed),
        "resampling_unit": "case",
    }
    return result


def compare_paired(
    left: Any,
    right: Any,
    *,
    metric: str = "score",
    seed: int,
    statistic: Statistic = "mean",
    n_resamples: int = DEFAULT_RESAMPLES,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    method: str = "bca",
    sensitivity: bool = True,
) -> dict[str, Any]:
    """Compare two runs by shared case identifier and return auditable deltas."""

    if metric.lower() in {"overall", "overall_score", "composite_score"}:
        raise ValueError("opaque overall scores are not valid comparison metrics")
    left_values, right_values, alignment = _aligned_values(left, right, metric)
    comparison = paired_bootstrap(
        left_values,
        right_values,
        seed=seed,
        statistic=statistic,
        n_resamples=n_resamples,
        confidence_level=confidence_level,
        method=method,
    )
    left_summary = summarize(left_values, metric=metric)
    right_summary = summarize(right_values, metric=metric)
    result: dict[str, Any] = {
        **comparison,
        **alignment,
        "metric": metric,
        "left_mean": left_summary["mean"],
        "right_mean": right_summary["mean"],
        "left_median": left_summary["median"],
        "right_median": right_summary["median"],
        "delta_mean": comparison["mean_delta"],
        "delta_median": comparison["median_delta"],
    }
    if sensitivity:
        result["sensitivity"] = sensitivity_tests(
            left_values,
            right_values,
            seed=seed,
            statistic=statistic,
            n_resamples=n_resamples,
            confidence_level=confidence_level,
            method=method,
        )
    return result


def delta_full_partial(
    full: Any,
    partial: Any,
    *,
    metric: str = "score",
    seed: int,
    statistic: Statistic = "mean",
    n_resamples: int = DEFAULT_RESAMPLES,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    method: str = "bca",
    sensitivity: bool = True,
) -> dict[str, Any]:
    """Calculate the explicit FULL minus PARTIAL paired delta.

    Only shared case IDs enter the comparison.  Missing cases are counted and
    surfaced in the result; they are never silently converted to zero.
    """

    result = compare_paired(
        full,
        partial,
        metric=metric,
        seed=seed,
        statistic=statistic,
        n_resamples=n_resamples,
        confidence_level=confidence_level,
        method=method,
        sensitivity=sensitivity,
    )
    result.update(
        {
            "comparison": "FULL-PARTIAL",
            "full_status": result.pop("left_status"),
            "partial_status": result.pop("right_status"),
            "full_run_id": result.pop("left_run_id"),
            "partial_run_id": result.pop("right_run_id"),
            "full_case_count": result.pop("left_case_count"),
            "partial_case_count": result.pop("right_case_count"),
            "full_expected_count": result.pop("left_expected_count"),
            "partial_expected_count": result.pop("right_expected_count"),
            "full_excluded_case_count": result.pop("left_excluded_case_count"),
            "partial_excluded_case_count": result.pop("right_excluded_case_count"),
            "direction": "positive means FULL exceeds PARTIAL",
        }
    )
    return result


def statistics_table(
    runs: Mapping[str, Any] | Sequence[Any],
    *,
    metrics: Iterable[str] | None = None,
    seed: int | None = None,
    n_resamples: int = DEFAULT_RESAMPLES,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    interval_method: str = "analytic",
) -> list[dict[str, Any]]:
    """Build long-form per-run/per-metric statistics with no opaque overall row."""

    if isinstance(runs, Mapping):
        run_items = list(runs.items())
    else:
        run_items = []
        for index, run in enumerate(runs):
            if isinstance(run, Mapping) and "run_id" in run:
                run_items.append((str(run["run_id"]), run))
            else:
                run_items.append((f"run-{index}", run))
    if not run_items:
        return []
    names = [str(metric) for metric in metrics] if metrics is not None else None
    output: list[dict[str, Any]] = []
    for run_offset, (run_name, run) in enumerate(run_items):
        records, status, envelope_run_id, expected_count = _records(run)
        run_metrics = names or _infer_metrics(records)
        if not run_metrics:
            raise ValueError(f"run {run_name!r} has no numeric metrics")
        for metric_offset, metric in enumerate(run_metrics):
            if metric.lower() in {"overall", "overall_score", "composite_score"}:
                raise ValueError("opaque overall scores are not valid table metrics")
            values, missing = _metric_values(records, metric)
            metric_seed = (
                None
                if seed is None
                else _validate_seed(seed) + run_offset * 1_000_003 + metric_offset
            )
            summary = summarize(
                values,
                seed=metric_seed,
                n_resamples=n_resamples,
                confidence_level=confidence_level,
                interval_method=interval_method,
                metric=metric,
            )
            output.append(
                {
                    "run_id": envelope_run_id or run_name,
                    "status": status,
                    "metric": metric,
                    "n": summary["n"],
                    "case_count": len(records),
                    "missing_case_count": missing,
                    "expected_count": expected_count,
                    "coverage": None
                    if expected_count is None
                    else len(records) / expected_count
                    if expected_count
                    else 1.0,
                    "mean": summary["mean"],
                    "median": summary["median"],
                    "sd": summary["sd"],
                    "ci_low": summary["ci_low"],
                    "ci_high": summary["ci_high"],
                    "ci_method": summary["mean_ci"]["method"],
                    "confidence_level": confidence_level,
                    "seed": metric_seed,
                }
            )
    return output


def render_markdown_table(rows: Sequence[Mapping[str, Any]]) -> str:
    """Render the long-form statistics table without introducing an overall score."""

    columns = ("run_id", "status", "metric", "n", "mean", "median", "ci_low", "ci_high")
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column)
            values.append(
                ""
                if value is None
                else f"{value:.6g}"
                if isinstance(value, float)
                else str(value)
            )
        body.append("| " + " | ".join(values) + " |")
    return "\n".join((header, separator, *body))


# Verb-oriented aliases keep the small public API discoverable for callers
# using either American or British spelling.
describe = summarize
summarise = summarize
build_statistics_table = statistics_table
compare_runs = compare_paired
full_partial_delta = delta_full_partial
paired_delta = paired_bootstrap


__all__ = [
    "DEFAULT_CONFIDENCE_LEVEL",
    "DEFAULT_RESAMPLES",
    "bootstrap_ci",
    "build_statistics_table",
    "case_statistics",
    "compare_paired",
    "compare_runs",
    "delta_full_partial",
    "describe",
    "full_partial_delta",
    "paired_bootstrap",
    "paired_delta",
    "per_case_table",
    "render_markdown_table",
    "sensibility_tests",
    "sensitivity_tests",
    "statistics_table",
    "summarise",
    "summarize",
]


# Backwards-friendly typo alias kept private in docs but exported for callers
# that used the Spanish-oriented name in early prototypes.
sensibility_tests = sensitivity_tests
