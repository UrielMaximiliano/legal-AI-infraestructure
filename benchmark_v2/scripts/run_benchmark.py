"""Run the independent benchmark-v2 evaluators over a case table.

The runner deliberately emits per-dimension records instead of a composite
legal score.  Missing source artifacts are represented as ``NOT_CALCULABLE``
and never as zeroes.  This makes a diagnostic run useful even when the raw
holdout PDFs, prompts, model responses, or retrieval cache are unavailable in
the checkout.

The input contract is intentionally permissive at the boundary.  A case may
use common aliases (``candidate``/``response``/``answer`` and
``gold``/``reference``/``references``); the evaluators themselves remain
strict and auditable once a case is mapped into their contracts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmark_v2.data.hashing import hash_records, sha256_file
from benchmark_v2.data.io import read_records, write_csv, write_jsonl
from benchmark_v2.evaluators.claims import evaluate as evaluate_claims
from benchmark_v2.evaluators.faithfulness import evaluate_faithfulness
from benchmark_v2.evaluators.legal_fields import LegalFieldsEvaluator
from benchmark_v2.evaluators.retrieval import evaluate_case as evaluate_retrieval_case
from benchmark_v2.evaluators.semantic import evaluate_case as evaluate_semantic_case
from benchmark_v2.evaluators.structure import evaluate_structure

CALCULATED = "CALCULATED"
NOT_CALCULABLE = "NOT_CALCULABLE"
PARTIAL = "PARTIAL"
FULL = "FULL"

_MISSING = object()
_CANDIDATE_KEYS = ("candidate", "response", "answer", "output", "prediction")
_PREDICTION_KEYS = ("prediction", "candidate", "output", "response", "answer")
_REFERENCE_KEYS = ("references", "reference", "gold", "gold_text", "reference_text")
_RETRIEVAL_KEYS = frozenset(
    {
        "retrieved",
        "retrieved_ids",
        "returned_ids",
        "results",
        "relevance",
        "relevant",
        "relevant_ids",
        "graded_relevance",
        "expected_items",
        "ground_truth_items",
    }
)


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _first(mapping: Mapping[str, Any], keys: Sequence[str], default: Any = _MISSING) -> Any:
    for key in keys:
        value = mapping.get(key, _MISSING)
        if value is not _MISSING and value is not None:
            return value
    return default


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        nested = _first(value, ("text", "answer", "response", "content", "summary"))
        if isinstance(nested, str):
            return nested
    return None


def _references(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Mapping):
        nested = _first(value, ("text", "reference", "answer", "content"))
        return _references(nested)
    if isinstance(value, (list, tuple)):
        return [item for item in (_text(item) for item in value) if item and item.strip()]
    return []


def _not_calculable(reason: str, *, case_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": NOT_CALCULABLE, "reason": reason}
    if case_id is not None:
        result["case_id"] = case_id
    return result


def _status(value: Any) -> str:
    if isinstance(value, Mapping):
        raw = value.get("status")
        if isinstance(raw, str) and raw:
            return raw
    return NOT_CALCULABLE


def _case_id(row: Mapping[str, Any], position: int) -> str | None:
    value = _first(row, ("case_id", "record_id", "id", "query_id"))
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _candidate(row: Mapping[str, Any]) -> Any:
    value = _first(row, _CANDIDATE_KEYS)
    return None if value is _MISSING else value


def _prediction(row: Mapping[str, Any]) -> Any:
    value = _first(row, _PREDICTION_KEYS)
    return None if value is _MISSING else value


def _gold(row: Mapping[str, Any]) -> Any:
    value = _first(row, _REFERENCE_KEYS)
    return None if value is _MISSING else value


def _evaluate_semantic(case_id: str | None, row: Mapping[str, Any], candidate: Any) -> dict[str, Any]:
    candidate_text = _text(candidate)
    references = _references(_gold(row))
    if not candidate_text or not references:
        return _not_calculable("candidate_or_reference_text_missing", case_id=case_id)
    return evaluate_semantic_case(
        {"case_id": case_id or "", "candidate": candidate_text, "references": references}
    )


def _evaluate_claims(case_id: str | None, row: Mapping[str, Any], prediction: Any) -> dict[str, Any]:
    gold = _gold(row)
    if gold is None:
        return _not_calculable("claims_gold_missing", case_id=case_id)
    result = evaluate_claims(prediction, gold)
    if isinstance(result, Mapping):
        return dict(result)
    return _not_calculable("claims_evaluator_returned_invalid_result", case_id=case_id)


def _evaluate_legal_fields(case_id: str | None, row: Mapping[str, Any], candidate: Any) -> dict[str, Any]:
    expected = _first(row, ("legal_fields", "expected_fields", "gold_fields"))
    if expected is _MISSING:
        gold = _gold(row)
        expected = gold if isinstance(gold, Mapping) else _MISSING
    if not isinstance(expected, Mapping):
        return _not_calculable("legal_fields_reference_missing", case_id=case_id)
    predicted = _first(row, ("predicted_fields", "candidate_fields", "answer_fields"))
    if predicted is _MISSING:
        predicted = candidate
    result = LegalFieldsEvaluator(
        fields=row.get("field_config") or row.get("fields"),
        required_fields=row.get("required_fields"),
        configurable_fields=row.get("configurable_fields"),
        field_config=row.get("field_config"),
    ).evaluate(expected, predicted)
    return dict(result) if isinstance(result, Mapping) else _not_calculable(
        "legal_fields_evaluator_returned_invalid_result", case_id=case_id
    )


def _evaluate_retrieval(case_id: str | None, row: Mapping[str, Any]) -> dict[str, Any]:
    nested = row.get("retrieval")
    payload: dict[str, Any] = dict(nested) if isinstance(nested, Mapping) else dict(row)
    if not any(key in payload for key in _RETRIEVAL_KEYS):
        return _not_calculable("retrieval_reference_missing", case_id=case_id)
    payload.setdefault("query_id", case_id or "")
    try:
        return dict(evaluate_retrieval_case(payload, ks=tuple(row.get("retrieval_ks", (3, 5)))))
    except (TypeError, ValueError, KeyError) as exc:
        return _not_calculable(f"retrieval_input_invalid:{exc}", case_id=case_id)


def _evaluate_faithfulness(case_id: str | None, row: Mapping[str, Any], prediction: Any) -> dict[str, Any]:
    answer = _text(prediction)
    if not answer:
        return _not_calculable("candidate_text_missing", case_id=case_id)
    context = _first(row, ("rag_context", "retrieval_trace", "context", "chunks"))
    evidence = row.get("evidence")
    if context is _MISSING:
        context = None
    if context is None and evidence is None:
        return _not_calculable("rag_evidence_missing", case_id=case_id)
    try:
        result = evaluate_faithfulness(
            answer=answer,
            context=context,
            rag_context=context,
            evidence=evidence,
            claims=row.get("claims"),
            threshold=float(row.get("faithfulness_threshold", 0.8)),
        )
    except (TypeError, ValueError, KeyError) as exc:
        return _not_calculable(f"faithfulness_input_invalid:{exc}", case_id=case_id)
    return dict(result) if isinstance(result, Mapping) else _not_calculable(
        "faithfulness_evaluator_returned_invalid_result", case_id=case_id
    )


def _evaluate_structure(case_id: str | None, row: Mapping[str, Any], candidate: Any) -> dict[str, Any]:
    if candidate is None:
        return _not_calculable("candidate_output_missing", case_id=case_id)
    try:
        return dict(
            evaluate_structure(
                candidate,
                schema=row.get("schema"),
                expected_format=row.get("expected_format"),
                required_fields=row.get("required_fields"),
                expected_citations=row.get("expected_citations"),
                allowed_citation_ids=row.get("allowed_citation_ids"),
                expected_evidence=row.get("expected_evidence"),
                evidence=row.get("evidence"),
                utility_score=row.get("utility_score"),
                latency_ms=row.get("latency_ms"),
                cost=row.get("cost"),
                trace=row.get("trace") or row.get("telemetry"),
            )
        )
    except (TypeError, ValueError, KeyError) as exc:
        return _not_calculable(f"structure_input_invalid:{exc}", case_id=case_id)


def _leakage_checks(rows: Sequence[Mapping[str, Any]], result_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ids = [row.get("case_id") for row in result_rows if row.get("case_id") is not None]
    duplicate_case_ids = sorted(item for item, count in Counter(ids).items() if count > 1)
    invalid_joins = sum(1 for row in result_rows if not row.get("case_id"))
    candidate_contains_reference = 0
    evidence_checked = 0
    for row, result in zip(rows, result_rows):
        candidate = _text(_candidate(row)) or ""
        if not candidate:
            continue
        declared = _first(
            row,
            ("excluded_pdf_text", "reference_text_for_leakage", "reference_content", "holdout_text"),
        )
        if isinstance(declared, str) and declared.strip():
            evidence_checked += 1
            if declared.strip().casefold() in candidate.casefold():
                candidate_contains_reference += 1
    return {
        "duplicate_case_ids": duplicate_case_ids,
        "duplicate_count": len(duplicate_case_ids),
        "invalid_joins": invalid_joins,
        "candidate_contains_reference": candidate_contains_reference,
        "reference_text_checks": evidence_checked,
        "status": "PASS" if not duplicate_case_ids and invalid_joins == 0 and candidate_contains_reference == 0 else "FAIL",
        "checks_not_calculable": evidence_checked == 0,
    }


def _human_row(row: Mapping[str, Any], case_id: str | None) -> dict[str, Any]:
    candidate = _candidate(row)
    reference = _gold(row)
    return {
        "case_id": case_id,
        "candidate": candidate,
        "reference": reference,
        "reviewer_1": {
            "organismo": None,
            "objeto": None,
            "persona_cargo": None,
            "dependencia": None,
            "fecha_plazo_vigencia": None,
            "normas_citadas": None,
            "articulos_resolutivos": None,
            "datos_criticos": None,
            "claims_tp": None,
            "claims_fp": None,
            "claims_fn": None,
            "faithfulness": None,
            "utility": None,
            "notes": None,
        },
        "reviewer_2": {
            "organismo": None,
            "objeto": None,
            "persona_cargo": None,
            "dependencia": None,
            "fecha_plazo_vigencia": None,
            "normas_citadas": None,
            "articulos_resolutivos": None,
            "datos_criticos": None,
            "claims_tp": None,
            "claims_fp": None,
            "claims_fn": None,
            "faithfulness": None,
            "utility": None,
            "notes": None,
        },
    }


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    commit = completed.stdout.strip()
    return commit or None


def run_benchmark(
    cases_path: str | Path | None = None,
    *,
    out_dir: str | Path,
    run_id: str = "benchmark-v2",
    expected_count: int | None = None,
    seed: int = 20260825,
    human_sample: int = 0,
    strict: bool = False,
) -> dict[str, Any]:
    """Execute the case-level V2 pipeline and return the summary envelope."""

    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source = Path(cases_path) if cases_path is not None else None
    rows: list[dict[str, Any]] = []
    input_error: str | None = None
    input_sha256: str | None = None
    if source is None:
        input_error = "input_cases_unavailable"
    elif not source.exists():
        input_error = f"input_cases_not_found:{source}"
    else:
        try:
            rows = [dict(row) for row in read_records(source)]
            input_sha256 = sha256_file(source)
        except (ImportError, OSError, TypeError, ValueError) as exc:
            input_error = f"input_cases_unreadable:{exc}"

    result_rows: list[dict[str, Any]] = []
    human_rows: list[dict[str, Any]] = []
    if input_error is None:
        for position, row in enumerate(rows):
            case_id = _case_id(row, position)
            candidate = _candidate(row)
            prediction = _prediction(row)
            result = {
                "case_id": case_id,
                "input_position": position,
                "coverage_status": "OBSERVED",
                "semantic": _evaluate_semantic(case_id, row, candidate),
                "claims": _evaluate_claims(case_id, row, prediction),
                "legal_fields": _evaluate_legal_fields(case_id, row, candidate),
                "retrieval": _evaluate_retrieval(case_id, row),
                "faithfulness": _evaluate_faithfulness(case_id, row, prediction),
                "structure": _evaluate_structure(case_id, row, candidate),
            }
            result_rows.append(result)
            if human_sample > 0:
                human_rows.append(_human_row(row, case_id))
    elif strict:
        raise FileNotFoundError(input_error)

    observed_count = len(result_rows)
    missing_count = max(0, expected_count - observed_count) if expected_count is not None else None
    if input_error is not None or observed_count == 0:
        status = NOT_CALCULABLE
    elif expected_count is not None and observed_count == expected_count:
        status = FULL
    else:
        status = PARTIAL

    dimensions: dict[str, dict[str, int]] = {}
    for dimension in ("semantic", "claims", "legal_fields", "retrieval", "faithfulness", "structure"):
        counts = Counter(_status(row[dimension]) for row in result_rows)
        dimensions[dimension] = dict(sorted(counts.items()))

    leakage = _leakage_checks(rows, result_rows) if result_rows else {
        "duplicate_case_ids": [],
        "duplicate_count": 0,
        "invalid_joins": 0,
        "candidate_contains_reference": 0,
        "reference_text_checks": 0,
        "status": "NOT_CALCULABLE",
        "checks_not_calculable": True,
    }
    reasons: list[str] = []
    if input_error:
        reasons.append(input_error)
    if expected_count is None:
        reasons.append("expected_count_not_declared")
    elif missing_count and observed_count:
        reasons.append("observed_cases_less_than_expected")
    if leakage["status"] == "FAIL":
        reasons.append("leakage_or_join_assertion_failed")

    metrics_path = output_dir / "metrics.jsonl"
    metrics_csv_path = output_dir / "metrics.csv"
    write_jsonl(metrics_path, result_rows)
    flat_rows = [
        {
            "case_id": row.get("case_id"),
            "input_position": row.get("input_position"),
            "coverage_status": row.get("coverage_status"),
            **{f"{dimension}_status": _status(row.get(dimension)) for dimension in dimensions},
        }
        for row in result_rows
    ]
    write_csv(
        metrics_csv_path,
        flat_rows,
        fieldnames=["case_id", "input_position", "coverage_status"]
        + [f"{dimension}_status" for dimension in dimensions],
    )
    human_sample = max(0, int(human_sample))
    if human_sample:
        human_rows = sorted(human_rows, key=lambda row: str(row.get("case_id")))[:human_sample]
    human_path = output_dir / "human_eval_template.jsonl"
    write_jsonl(human_path, human_rows)

    summary: dict[str, Any] = {
        "schema_version": "benchmark-v2.run-summary.v1",
        "run_id": run_id,
        "status": status,
        "expected_count": expected_count,
        "observed_count": observed_count,
        "missing_count": missing_count,
        "dimensions": dimensions,
        "leakage_checks": leakage,
        "not_calculable_reasons": sorted(set(reasons)),
        "opaque_overall_score": False,
        "overall_score": None,
        "input": {"path": str(source) if source else None, "sha256": input_sha256},
        "artifacts": {
            "metrics_jsonl": str(metrics_path),
            "metrics_csv": str(metrics_csv_path),
            "human_eval_template": str(human_path),
        },
    }
    summary_path = output_dir / "summary.json"
    _write_json(summary_path, summary)
    manifest = {
        "schema_version": "benchmark-v2.run-manifest.v1",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "seed": seed,
        "code": {"commit": _git_commit()},
        "input": {"path": str(source) if source else None, "sha256": input_sha256, "records_sha256": hash_records(rows)},
        "status": status,
        "expected_count": expected_count,
        "observed_count": observed_count,
        "artifacts": {
            name: str(path)
            for name, path in {
                "summary": summary_path,
                "metrics_jsonl": metrics_path,
                "metrics_csv": metrics_csv_path,
                "human_eval_template": human_path,
            }.items()
        },
    }
    _write_json(output_dir / "run_manifest.json", manifest)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, help="JSONL, CSV, or optional Parquet case table")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-id", default="benchmark-v2")
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--human-sample", type=int, default=0)
    parser.add_argument("--strict", action="store_true", help="fail when the input table is unavailable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = run_benchmark(
        args.cases,
        out_dir=args.out_dir,
        run_id=args.run_id,
        expected_count=args.expected_count,
        seed=args.seed,
        human_sample=args.human_sample,
        strict=args.strict,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
