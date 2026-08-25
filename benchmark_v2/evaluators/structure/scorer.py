"""Structural and utility metrics for benchmark-v2 outputs.

This evaluator intentionally reports a vector of dimensions.  It checks that
an output can be parsed as JSON, conforms to an optional JSON Schema, contains
the expected fields, follows the requested top-level format, and uses known
citation/evidence identifiers.  Human usefulness and operational telemetry
are reported separately; neither is folded into a legal correctness score.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from statistics import fmean
from typing import Any

from .schema import JSONSchema, is_schema_valid, required_paths, validate_json_schema


class StructureEvaluationError(ValueError):
    """Raised for invalid evaluator configuration, not for a bad model output."""


_MISSING = object()
_SOURCE_CATALOG_KEYS = frozenset(
    {"sources", "available_sources", "source_catalog", "evidence_catalog"}
)
_CITATION_KEYS = frozenset(
    {
        "citation",
        "citations",
        "citation_id",
        "citation_ids",
        "reference",
        "references",
        "reference_id",
        "reference_ids",
        "source_id",
        "source_ids",
        "evidence_id",
        "evidence_ids",
    }
)
_UTILITY_KEYS = frozenset(
    {"utility_score", "usefulness_score", "utility", "usefulness", "human_utility"}
)
_LATENCY_KEYS = frozenset(
    {"latency_ms", "duration_ms", "elapsed_ms", "response_time_ms", "inference_latency_ms"}
)
_COST_KEYS = frozenset({"cost", "cost_usd", "total_cost", "compute_cost"})
_TOKEN_KEYS = frozenset(
    {"input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens"}
)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _parse_json(value: Any) -> tuple[Any | None, str | None]:
    """Parse and round-trip an output, rejecting NaN/Infinity and non-JSON values."""

    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            return None, f"output is not UTF-8: {exc}"
    try:
        if isinstance(value, str):
            parsed = json.loads(value, parse_constant=_reject_constant)
        else:
            # Round-trip to ensure mappings and scalar values are JSON values.
            encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
            parsed = json.loads(encoded, parse_constant=_reject_constant)
    except (TypeError, ValueError, UnicodeError) as exc:
        return None, f"output is not valid JSON: {exc}"
    return parsed, None


def _lookup(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return bool(value)
    return True


def _normalise_fields(value: Iterable[str] | Mapping[str, Any] | str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(str(key) for key in value)
    return tuple(str(item) for item in value)


def _format_valid(value: Any, expected: Any) -> bool:
    if isinstance(expected, Mapping):
        errors = validate_json_schema(value, expected)
        return not errors
    if isinstance(expected, str):
        normalized = expected.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"json", "any", "value"}:
            return True
        if normalized in {"object", "dict", "mapping", "json_object"}:
            return isinstance(value, Mapping)
        if normalized in {"array", "list", "json_array"}:
            return isinstance(value, list)
        if normalized in {"string", "text"}:
            return isinstance(value, str)
        if normalized in {"number", "float"}:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if normalized == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if normalized in {"boolean", "bool"}:
            return isinstance(value, bool)
        if normalized == "null":
            return value is None
        raise StructureEvaluationError(f"unsupported expected format: {expected!r}")
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        return any(_format_valid(value, option) for option in expected)
    if callable(expected):
        return bool(expected(value))
    raise StructureEvaluationError("expected_format must be a string, schema, or callable")


def _string_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, str):
        if value.strip():
            result.add(value.strip())
    elif isinstance(value, Mapping):
        for key in ("citation_id", "source_id", "evidence_id", "reference_id", "id"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                result.add(item.strip())
        for item in value.values():
            if isinstance(item, (list, tuple, set, frozenset)):
                result.update(_string_ids(item))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            result.update(_string_ids(item))
    return result


def _used_citation_ids(value: Any, *, parent_key: str = "") -> set[str]:
    """Collect IDs referenced by the answer, excluding its source catalog."""

    if isinstance(value, Mapping):
        result: set[str] = set()
        for raw_key, item in value.items():
            key = str(raw_key).lower()
            if key in _SOURCE_CATALOG_KEYS:
                continue
            if key in _CITATION_KEYS:
                result.update(_string_ids(item))
            elif isinstance(item, (Mapping, list, tuple, set, frozenset)):
                result.update(_used_citation_ids(item, parent_key=key))
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        result: set[str] = set()
        for item in value:
            result.update(_used_citation_ids(item, parent_key=parent_key))
        return result
    return set()


def _catalog_citation_ids(value: Any, *, in_catalog: bool = False) -> set[str]:
    if isinstance(value, Mapping):
        result: set[str] = set()
        for raw_key, item in value.items():
            key = str(raw_key).lower()
            child_catalog = in_catalog or key in _SOURCE_CATALOG_KEYS or key in {
                "evidence", "references"
            }
            if child_catalog and key in {
                "citation_id", "source_id", "evidence_id", "reference_id", "id"
            }:
                result.update(_string_ids(item))
            if isinstance(item, (Mapping, list, tuple, set, frozenset)):
                result.update(_catalog_citation_ids(item, in_catalog=child_catalog))
        return result
    if in_catalog and isinstance(value, (list, tuple, set, frozenset)):
        result: set[str] = set()
        for item in value:
            result.update(_catalog_citation_ids(item, in_catalog=True))
        return result
    return set()


def _expected_ids(value: Any) -> set[str]:
    """Flatten expected citation/evidence declarations to stable IDs."""

    if value is None:
        return set()
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, Mapping):
        result = set()
        # Mapping declarations often use claim IDs as keys.  Only values are
        # evidence identifiers, except for explicit identifier-shaped fields.
        for key, item in value.items():
            if str(key).lower() in {
                "citation_id", "source_id", "evidence_id", "reference_id", "id"
            }:
                result.update(_string_ids(item))
            else:
                result.update(_expected_ids(item))
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        result = set()
        for item in value:
            result.update(_expected_ids(item))
        return result
    return set()


def _evidence_spans(value: Any, *, in_evidence: bool = False) -> dict[str, bool]:
    """Return citation IDs and whether each one has a non-empty span."""

    if isinstance(value, Mapping):
        result: dict[str, bool] = {}
        for raw_key, item in value.items():
            key = str(raw_key).lower()
            child_evidence = in_evidence or key in {
                "sources", "evidence", "references", "source_catalog", "evidence_catalog"
            }
            if child_evidence and key in {
                "citation_id", "source_id", "evidence_id", "reference_id", "id"
            }:
                ids = _string_ids(item)
                span = any(
                    _nonempty(value.get(span_key))
                    for span_key in ("span", "quote", "excerpt", "passage", "page", "start", "end")
                )
                result.update({identifier: span for identifier in ids})
            if isinstance(item, (Mapping, list, tuple, set, frozenset)):
                result.update(_evidence_spans(item, in_evidence=child_evidence))
        return result
    if in_evidence and isinstance(value, (list, tuple, set, frozenset)):
        result: dict[str, bool] = {}
        for item in value:
            result.update(_evidence_spans(item, in_evidence=True))
        return result
    return {}


def _first_key(value: Any, keys: frozenset[str]) -> Any:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            if str(raw_key).lower() in keys:
                return item
        for item in value.values():
            found = _first_key(item, keys)
            if found is not _MISSING:
                return found
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            found = _first_key(item, keys)
            if found is not _MISSING:
                return found
    return _MISSING


def _nonnegative_number(value: Any, label: str, errors: list[str]) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{label} must be a non-negative number")
        return None
    if not math.isfinite(float(value)) or value < 0:
        errors.append(f"{label} must be a finite non-negative number")
        return None
    return value


def _normalise_cost(value: Any, errors: list[str]) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        amount = value.get("amount", value.get("value", value.get("cost", _MISSING)))
        if amount is _MISSING:
            errors.append("cost mapping requires amount/value")
            return None
        numeric = _nonnegative_number(amount, "cost", errors)
        result: dict[str, Any] = {"amount": numeric}
        currency = value.get("currency", value.get("unit"))
        if currency is not None:
            result["currency"] = str(currency)
        for key in ("provider", "pricing_version"):
            if key in value:
                result[key] = value[key]
        return result
    return _nonnegative_number(value, "cost", errors)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def _mean(values: Iterable[Any]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return fmean(numbers) if numbers else None


def _metric_dict(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "json_valid": result.get("json_valid"),
        "schema_valid": result.get("schema_valid"),
        "completeness": result.get("completeness"),
        "format_valid": result.get("format_valid"),
        "citation_precision": result.get("citation_precision"),
        "citation_recall": result.get("citation_recall"),
        "evidence_coverage": result.get("evidence_coverage"),
        "invented_citation_rate": result.get("invented_citation_rate"),
        "utility_score": result.get("utility_score"),
    }


def score_structure(
    output: Any,
    *,
    schema: JSONSchema | str | None = None,
    expected_schema: JSONSchema | str | None = None,
    expected_format: Any = None,
    format_spec: Any = None,
    required_fields: Iterable[str] | Mapping[str, Any] | str | None = None,
    expected_fields: Iterable[str] | Mapping[str, Any] | str | None = None,
    expected_count: int | None = None,
    expected_citations: Any = None,
    allowed_citation_ids: Iterable[str] | None = None,
    citations: Any = None,
    expected_evidence: Any = None,
    evidence: Any = None,
    utility_score: float | int | None = None,
    usefulness_score: float | int | None = None,
    utility_scale: tuple[float, float] = (1.0, 5.0),
    latency_ms: float | int | None = None,
    cost: Any = None,
    trace: Mapping[str, Any] | None = None,
    telemetry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one model output without producing a legal correctness aggregate.

    ``schema`` and ``expected_format`` are optional because not every benchmark
    dimension has a JSON contract.  A missing reference produces ``None`` for
    metrics that cannot be inferred honestly, rather than a fabricated zero.
    """

    if schema is not None and expected_schema is not None:
        raise StructureEvaluationError("pass schema or expected_schema, not both")
    schema_value: JSONSchema | None = schema if schema is not None else expected_schema
    if isinstance(schema_value, str):
        try:
            loaded = json.loads(schema_value)
        except (TypeError, ValueError) as exc:
            raise StructureEvaluationError("schema is not valid JSON") from exc
        if not isinstance(loaded, Mapping):
            raise StructureEvaluationError("schema must be a JSON object")
        schema_value = loaded
    if schema_value is not None and not isinstance(schema_value, Mapping):
        raise StructureEvaluationError("schema must be a JSON object")
    if expected_format is not None and format_spec is not None:
        raise StructureEvaluationError("pass expected_format or format_spec, not both")
    format_value = expected_format if expected_format is not None else format_spec

    parsed, parse_error = _parse_json(output)
    json_valid = parse_error is None
    errors: list[str] = [] if parse_error is None else [parse_error]
    schema_errors: list[str] = []
    if json_valid and schema_value is not None:
        schema_errors = validate_json_schema(parsed, schema_value)
        errors.extend(schema_errors)
    schema_valid = json_valid and (not schema_errors if schema_value is not None else True)

    if format_value is not None:
        format_valid = json_valid and _format_valid(parsed, format_value)
    elif schema_value is not None:
        # The schema's root type is the expected format when a format wasn't
        # separately supplied.  A schema with no root type has no format claim.
        format_valid = schema_valid if "type" in schema_value else None
    else:
        format_valid = None

    required = _normalise_fields(required_fields if required_fields is not None else expected_fields)
    if not required and schema_value is not None:
        required = required_paths(schema_value)
    missing: list[str] = []
    if required and json_valid:
        for path in required:
            if _lookup(parsed, path) is _MISSING or not _nonempty(_lookup(parsed, path)):
                missing.append(path)
        completeness: float | None = (len(required) - len(missing)) / len(required)
    elif required:
        missing = list(required)
        completeness = 0.0
    else:
        completeness = None

    count_actual: int | None = None
    if json_valid:
        if isinstance(parsed, list):
            count_actual = len(parsed)
        elif isinstance(parsed, Mapping):
            for key in ("records", "results", "cases", "items"):
                candidate = parsed.get(key)
                if isinstance(candidate, list):
                    count_actual = len(candidate)
                    break
    if expected_count is not None:
        if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 0:
            raise StructureEvaluationError("expected_count must be a non-negative integer")
        count_score = (
            1.0 if count_actual == expected_count else 0.0
        ) if count_actual is not None else 0.0
        completeness = count_score if completeness is None else fmean((completeness, count_score))
    required_sections_present = completeness == 1.0 if completeness is not None else None

    allowed = set(str(item).strip() for item in allowed_citation_ids or () if str(item).strip())
    if not allowed and json_valid:
        allowed = _catalog_citation_ids(parsed)
    expected_citation_set = _expected_ids(expected_citations if expected_citations is not None else citations)
    # A gold citation declaration is not an allow-list when the answer also
    # exposes a source catalog: an answer cannot make an invented ID valid by
    # merely naming it as expected.  When no catalog exists, the declaration
    # is the only available reference and can serve as the allow-list.
    if expected_citation_set and not allowed:
        allowed.update(expected_citation_set)
    used = _used_citation_ids(parsed) if json_valid else set()
    valid_used = used & allowed
    citation_precision = len(valid_used) / len(used) if used and allowed else None
    citation_recall = (
        len(used & expected_citation_set) / len(expected_citation_set)
        if expected_citation_set
        else None
    )
    invented_citation_rate = len(used - allowed) / len(used) if used and allowed else None

    candidate_spans = _evidence_spans(parsed) if json_valid else {}
    expected_evidence_set = _expected_ids(expected_evidence)
    if expected_evidence_set:
        evidence_coverage = len(used & expected_evidence_set) / len(expected_evidence_set)
    elif used and candidate_spans:
        evidence_coverage = sum(bool(candidate_spans.get(item)) for item in used) / len(used)
    else:
        evidence_coverage = None
    if evidence is not None:
        evidence_ids = _expected_ids(evidence)
        if evidence_ids and used:
            allowed.update(evidence_ids)
            citation_precision = len(used & allowed) / len(used)

    utility = utility_score if utility_score is not None else usefulness_score
    if utility is None and json_valid:
        found = _first_key(parsed, _UTILITY_KEYS)
        if found is not _MISSING and not isinstance(found, Mapping):
            utility = found
        elif isinstance(found, Mapping):
            utility = found.get("score", found.get("value"))
    utility_value: float | None = None
    utility_normalized: float | None = None
    if utility is not None:
        if isinstance(utility, bool) or not isinstance(utility, (int, float)):
            errors.append("utility_score must be numeric")
        elif not math.isfinite(float(utility)):
            errors.append("utility_score must be finite")
        else:
            low, high = utility_scale
            if high <= low:
                raise StructureEvaluationError("utility_scale maximum must exceed minimum")
            if utility < low or utility > high:
                errors.append(f"utility_score must be between {low:g} and {high:g}")
            else:
                utility_value = float(utility)
                utility_normalized = (utility_value - low) / (high - low)

    merged_trace: dict[str, Any] = {}
    if isinstance(telemetry, Mapping):
        merged_trace.update(telemetry)
    if isinstance(trace, Mapping):
        merged_trace.update(trace)
    if latency_ms is None:
        found_latency = _first_key(merged_trace, _LATENCY_KEYS)
        if found_latency is _MISSING and json_valid:
            found_latency = _first_key(parsed, _LATENCY_KEYS)
        latency_ms = None if found_latency is _MISSING else found_latency
    if cost is None:
        found_cost = _first_key(merged_trace, _COST_KEYS)
        if found_cost is _MISSING and json_valid:
            found_cost = _first_key(parsed, _COST_KEYS)
        cost = None if found_cost is _MISSING else found_cost
    trace_errors: list[str] = []
    latency_value = _nonnegative_number(latency_ms, "latency_ms", trace_errors)
    cost_value = _normalise_cost(cost, trace_errors)
    token_values: dict[str, float | int] = {}
    for token_key in _TOKEN_KEYS:
        found = _first_key(merged_trace, frozenset({token_key}))
        if found is _MISSING and json_valid:
            found = _first_key(parsed, frozenset({token_key}))
        if found is not _MISSING:
            numeric = _nonnegative_number(found, token_key, trace_errors)
            if numeric is not None:
                token_values[token_key] = numeric
    errors.extend(trace_errors)
    traceability = {
        "latency_ms": latency_value,
        "cost": cost_value,
        "tokens": token_values or None,
        "latency_present": latency_value is not None,
        "cost_present": cost_value is not None,
        "tokens_present": bool(token_values),
    }

    result: dict[str, Any] = {
        "json_valid": json_valid,
        "schema_valid": schema_valid,
        "schema_errors": schema_errors,
        "format_valid": format_valid,
        "format_expected": format_value,
        "required_fields": list(required),
        "missing_fields": missing,
        "completeness": completeness,
        "required_sections_present": required_sections_present,
        "required_sections_rate": completeness,
        "expected_count": expected_count,
        "actual_count": count_actual,
        "used_citations": sorted(used),
        "allowed_citations": sorted(allowed),
        "citation_precision": citation_precision,
        "citation_recall": citation_recall,
        "evidence_coverage": evidence_coverage,
        "invented_citation_rate": invented_citation_rate,
        "utility_score": utility_value,
        "usefulness_score": utility_value,
        "utility_normalized": utility_normalized,
        "latency_ms": latency_value,
        "cost": cost_value,
        "traceability": traceability,
        "errors": errors,
        "warnings": [],
    }
    result["metrics"] = _metric_dict(result)
    result["score_vector"] = {
        "structure": {
            "json_valid": float(json_valid),
            "schema_valid": float(schema_valid),
            "completeness": completeness,
            "format_valid": None if format_valid is None else float(format_valid),
        },
        "citations": {
            "precision": citation_precision,
            "recall": citation_recall,
            "evidence_coverage": evidence_coverage,
            "invented_rate": invented_citation_rate,
        },
        "utility": {"score": utility_value, "normalized": utility_normalized},
    }
    # Names used by the RAG evaluation contract remain available as aliases,
    # while a single output has a boolean rather than a misleading rate.
    result["schema_valid_rate"] = float(schema_valid)
    result["format_valid_rate"] = None if format_valid is None else float(format_valid)
    return result


def evaluate_structure(output: Any, **kwargs: Any) -> dict[str, Any]:
    """Alias with a verb-oriented name for one-output evaluation."""

    return score_structure(output, **kwargs)


def score_output(output: Any, **kwargs: Any) -> dict[str, Any]:
    """Compatibility alias for callers that call model responses outputs."""

    return score_structure(output, **kwargs)


def _case_output(case: Mapping[str, Any]) -> Any:
    for key in ("output", "response", "result", "answer", "prediction"):
        if key in case:
            return case[key]
    return case


def aggregate_scores(scores: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate independent structural dimensions without a legal total."""

    values = tuple(scores)
    latencies = [float(item["latency_ms"]) for item in values if item.get("latency_ms") is not None]
    costs: list[float] = []
    for item in values:
        cost_value = item.get("cost")
        if isinstance(cost_value, Mapping):
            amount = cost_value.get("amount")
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                costs.append(float(amount))
        elif isinstance(cost_value, (int, float)) and not isinstance(cost_value, bool):
            costs.append(float(cost_value))

    metric_values = {
        "schema_valid_rate": _mean(float(bool(item.get("schema_valid"))) for item in values),
        "json_valid_rate": _mean(float(bool(item.get("json_valid"))) for item in values),
        "required_sections_rate": _mean(item.get("required_sections_rate") for item in values),
        "format_valid_rate": _mean(item.get("format_valid_rate") for item in values),
        "citation_precision": _mean(item.get("citation_precision") for item in values),
        "citation_recall": _mean(item.get("citation_recall") for item in values),
        "evidence_coverage": _mean(item.get("evidence_coverage") for item in values),
        "invented_citation_rate": _mean(item.get("invented_citation_rate") for item in values),
    }
    utility_values = [item.get("utility_score") for item in values if item.get("utility_score") is not None]
    telemetry = {
        "latency_ms": (
            {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "max": max(latencies),
            }
            if latencies
            else None
        ),
        "cost": (
            {"total": sum(costs), "average": fmean(costs), "observed": len(costs)}
            if costs
            else None
        ),
        "latency_coverage": len(latencies) / len(values) if values else None,
        "cost_coverage": len(costs) / len(values) if values else None,
    }
    return {
        "case_count": len(values),
        "metrics": metric_values,
        "schema_valid_rate": metric_values["schema_valid_rate"],
        "required_sections_rate": metric_values["required_sections_rate"],
        "format_valid_rate": metric_values["format_valid_rate"],
        "citation_precision": metric_values["citation_precision"],
        "citation_recall": metric_values["citation_recall"],
        "evidence_coverage": metric_values["evidence_coverage"],
        "invented_citation_rate": metric_values["invented_citation_rate"],
        "utility": {
            "evaluated": len(utility_values),
            "average": fmean(float(item) for item in utility_values) if utility_values else None,
        },
        "traceability": telemetry,
        "latency_ms": telemetry["latency_ms"],
        "cost": telemetry["cost"],
    }


def evaluate_cases(
    cases: Iterable[Any],
    *,
    schema: JSONSchema | str | None = None,
    expected_format: Any = None,
    required_fields: Iterable[str] | Mapping[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Score a collection of cases and aggregate only independent dimensions.

    A case mapping may provide per-case ``schema``, ``expected_citations``,
    ``expected_evidence``, ``utility_score``, ``latency_ms`` and ``cost``.
    """

    scores: list[dict[str, Any]] = []
    for case in cases:
        if isinstance(case, Mapping):
            local = dict(case)
            output = _case_output(local)
            options = {
                "schema": local.pop("schema", schema),
                "expected_format": local.pop("expected_format", expected_format),
                "required_fields": local.pop("required_fields", required_fields),
                "expected_citations": local.pop("expected_citations", local.pop("citations", None)),
                "allowed_citation_ids": local.pop("allowed_citation_ids", None),
                "expected_evidence": local.pop("expected_evidence", None),
                "evidence": local.pop("evidence", None),
                "utility_score": local.pop("utility_score", local.pop("usefulness_score", None)),
                "latency_ms": local.pop("latency_ms", None),
                "cost": local.pop("cost", None),
                "trace": local.pop("trace", local.pop("telemetry", None)),
            }
        else:
            output = case
            options = {
                "schema": schema,
                "expected_format": expected_format,
                "required_fields": required_fields,
            }
        scores.append(score_structure(output, **options))
    aggregate = aggregate_scores(scores)
    aggregate["cases"] = scores
    return aggregate


def score_cases(cases: Iterable[Any], **kwargs: Any) -> dict[str, Any]:
    """Compatibility alias for batch evaluation."""

    return evaluate_cases(cases, **kwargs)


__all__ = [
    "StructureEvaluationError",
    "aggregate_scores",
    "evaluate_cases",
    "evaluate_structure",
    "score_cases",
    "score_output",
    "score_structure",
]
