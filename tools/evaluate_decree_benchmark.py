#!/usr/bin/env python3
"""Evaluate decree-generation runs with auditable legal metrics.

The evaluator deliberately requires human adjudication for legal metrics.  It
does not infer legal truth from section presence, citations, or string overlap.
Those are useful engineering metrics, but they are not Accuracy/Precision/
Recall for a decree.

Gold manifest (JSONL) shape:

    {
      "case_number": 1,
      "reference_pdf": "200924.pdf",
      "reference_sha256": "...",
      "gold_facts": [
        {"fact_id": "f1", "field": "organismo", "text": "..."}
      ],
      "adjudication": {
        "fields": {
          "organismo": {"score": 1, "note": "..."},
          "objeto": {"score": 0.5},
          "persona_cargo": {"score": 0},
          "dependencia": {"score": 1},
          "fecha_plazo_vigencia": {"score": 1},
          "normas_citadas": {"score": 0.5},
          "articulos_resolutivos": {"score": 1},
          "datos_criticos": {"score": 0}
        },
        "fact_verdicts": [
          {"fact_id": "f1", "status": "TP"},
          {"fact_id": "f2", "status": "FN"}
        ],
        "false_positive_facts": [
          {"fact_id": "fp1", "field": "objeto", "note": "..."}
        ]
      }
    }

Only adjudicated records produce legal metrics.  Missing annotations are
reported as NOT_CALCULABLE, never as zero.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


FIELD_NAMES = (
    "organismo",
    "objeto",
    "persona_cargo",
    "dependencia",
    "fecha_plazo_vigencia",
    "normas_citadas",
    "articulos_resolutivos",
    "datos_criticos",
)
VALID_FIELD_SCORES = {0.0, 0.5, 1.0}
VALID_FACT_STATUSES = {"TP", "FN"}
THRESHOLDS = (
    (0.90, "excelente"),
    (0.75, "bueno"),
    (0.60, "aceptable_con_revision"),
    (0.40, "flojo"),
    (0.00, "malo"),
)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_no}: expected an object")
                records.append(value)
        return records

    value = _read_json(path)
    if isinstance(value, list):
        if not all(isinstance(item, dict) for item in value):
            raise ValueError(f"{path}: expected an array of objects")
        return value
    if isinstance(value, dict):
        return [value]
    raise ValueError(f"{path}: expected an object, array, or JSONL")


def _case_number(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid case_number: {value!r}") from exc


def _run_name(case_path: Path) -> str:
    if case_path.parent.name == "cases":
        return case_path.parent.parent.name
    return case_path.parent.name


def _iter_case_files(paths: Iterable[Path]) -> Iterable[Path]:
    for source in paths:
        if source.is_file() and source.name.startswith("case-"):
            yield source
            continue
        if source.is_dir():
            yield from sorted(source.rglob("case-*.json"))


def _load_runs(paths: list[Path]) -> dict[str, dict[int, dict[str, Any]]]:
    runs: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for case_path in _iter_case_files(paths):
        try:
            record = _read_json(case_path)
            case_number = _case_number(record.get("case_number"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"warning: skipping {case_path}: {exc}", file=sys.stderr)
            continue
        run = _run_name(case_path)
        if case_number in runs[run]:
            print(
                f"warning: duplicate run/case {run}/{case_number}; keeping first",
                file=sys.stderr,
            )
            continue
        runs[run][case_number] = {
            "record": record,
            "path": str(case_path),
        }
    return dict(runs)


def _load_gold(path: Path) -> dict[int, dict[str, Any]]:
    records = _read_records(path)
    result: dict[int, dict[str, Any]] = {}
    for record in records:
        number = _case_number(record.get("case_number"))
        if number in result:
            raise ValueError(f"duplicate gold case_number: {number}")
        result[number] = record
    return result


def _score_value(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("score")
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if score in VALID_FIELD_SCORES else None


def _field_scores(gold: dict[str, Any]) -> tuple[dict[str, float], str | None]:
    adjudication = gold.get("adjudication")
    if not isinstance(adjudication, dict):
        return {}, "missing_adjudication"
    fields = adjudication.get("fields")
    if not isinstance(fields, dict):
        return {}, "missing_field_adjudication"
    scores: dict[str, float] = {}
    for field in FIELD_NAMES:
        score = _score_value(fields.get(field))
        if score is None:
            return {}, f"missing_or_invalid_field_score:{field}"
        scores[field] = score
    return scores, None


def _fact_counts(gold: dict[str, Any]) -> tuple[dict[str, int], str | None]:
    facts = gold.get("gold_facts")
    adjudication = gold.get("adjudication")
    if not isinstance(facts, list) or not facts:
        return {}, "missing_gold_facts"
    if not isinstance(adjudication, dict):
        return {}, "missing_adjudication"
    verdicts = adjudication.get("fact_verdicts")
    if not isinstance(verdicts, list):
        return {}, "missing_fact_verdicts"

    expected_ids: list[str] = []
    for fact in facts:
        if not isinstance(fact, dict) or not fact.get("fact_id"):
            return {}, "invalid_gold_fact"
        expected_ids.append(str(fact["fact_id"]))
    if len(set(expected_ids)) != len(expected_ids):
        return {}, "duplicate_gold_fact_id"

    verdict_by_id: dict[str, str] = {}
    for verdict in verdicts:
        if not isinstance(verdict, dict) or not verdict.get("fact_id"):
            return {}, "invalid_fact_verdict"
        fact_id = str(verdict["fact_id"])
        status = str(verdict.get("status", "")).upper()
        if status not in VALID_FACT_STATUSES:
            return {}, f"invalid_fact_status:{status}"
        if fact_id in verdict_by_id:
            return {}, f"duplicate_fact_verdict:{fact_id}"
        verdict_by_id[fact_id] = status
    if set(verdict_by_id) != set(expected_ids):
        return {}, "fact_verdicts_do_not_cover_all_gold_facts"

    false_positives = adjudication.get("false_positive_facts", [])
    if not isinstance(false_positives, list):
        return {}, "invalid_false_positive_facts"
    counts = {
        "tp": sum(status == "TP" for status in verdict_by_id.values()),
        "fn": sum(status == "FN" for status in verdict_by_id.values()),
        "fp": len(false_positives),
    }
    return counts, None


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _rating(value: float | None) -> str | None:
    if value is None:
        return None
    for minimum, label in THRESHOLDS:
        if value >= minimum:
            return label
    return "malo"


def _evaluate_case(
    run_name: str,
    case_number: int,
    output: dict[str, Any] | None,
    gold: dict[str, Any] | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run": run_name,
        "case_number": case_number,
        "output_present": output is not None,
        "reference_pdf": gold.get("reference_pdf") if gold else None,
        "reference_pdf_match": None,
        "reference_hash_match": None,
        "field_status": "NOT_CALCULABLE",
        "fact_status": "NOT_CALCULABLE",
        "status": "NOT_CALCULABLE",
        "accuracy": None,
        "accuracy_rating": None,
        "tp": None,
        "fp": None,
        "fn": None,
        "precision": None,
        "recall": None,
        "f1": None,
        "reason": None,
    }
    if output is None:
        row["reason"] = "missing_output"
        return row
    if gold is None:
        row["reason"] = "missing_gold_record"
        return row

    output_record = output["record"]
    gold_pdf = gold.get("reference_pdf")
    output_pdf = output_record.get("reference_pdf")
    if gold_pdf is not None and output_pdf is not None:
        row["reference_pdf_match"] = str(gold_pdf) == str(output_pdf)
    gold_hash = gold.get("reference_sha256")
    output_hash = output_record.get("reference_sha256")
    if gold_hash and output_hash:
        row["reference_hash_match"] = str(gold_hash).lower() == str(output_hash).lower()

    scores, field_error = _field_scores(gold)
    if field_error is None:
        accuracy = sum(scores.values()) / len(FIELD_NAMES)
        row.update(
            {
                "field_status": "CALCULATED",
                "accuracy": accuracy,
                "accuracy_rating": _rating(accuracy),
            }
        )
    else:
        row["reason"] = field_error

    counts, fact_error = _fact_counts(gold)
    if fact_error is None:
        precision = _ratio(counts["tp"], counts["tp"] + counts["fp"])
        recall = _ratio(counts["tp"], counts["tp"] + counts["fn"])
        row.update(
            {
                "fact_status": "CALCULATED",
                "tp": counts["tp"],
                "fp": counts["fp"],
                "fn": counts["fn"],
                "precision": precision,
                "recall": recall,
                "f1": _f1(precision, recall),
            }
        )
    elif row["reason"] is None:
        row["reason"] = fact_error

    if row["field_status"] == "CALCULATED" and row["fact_status"] == "CALCULATED":
        row["status"] = "CALCULATED"
    elif row["field_status"] == "CALCULATED" or row["fact_status"] == "CALCULATED":
        row["status"] = "PARTIAL"
    return row


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    field_rows = [row for row in rows if row["field_status"] == "CALCULATED"]
    fact_rows = [row for row in rows if row["fact_status"] == "CALCULATED"]
    tp = sum(int(row["tp"]) for row in fact_rows)
    fp = sum(int(row["fp"]) for row in fact_rows)
    fn = sum(int(row["fn"]) for row in fact_rows)
    micro_precision = _ratio(tp, tp + fp)
    micro_recall = _ratio(tp, tp + fn)
    return {
        "cases_total": len(rows),
        "cases_field_annotated": len(field_rows),
        "cases_fact_annotated": len(fact_rows),
        "legal_metrics_status": "CALCULATED" if field_rows and fact_rows else "NOT_CALCULABLE",
        "accuracy_macro": _mean([float(row["accuracy"]) for row in field_rows]),
        "accuracy_rating": _rating(_mean([float(row["accuracy"]) for row in field_rows])),
        "facts_micro": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": micro_precision,
            "recall": micro_recall,
            "f1": _f1(micro_precision, micro_recall),
        },
        "facts_macro": {
            "precision": _mean([float(row["precision"]) for row in fact_rows]),
            "recall": _mean([float(row["recall"]) for row in fact_rows]),
            "f1": _mean([float(row["f1"]) for row in fact_rows]),
        },
    }


def _write_outputs(output_dir: Path, result: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "legal-evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rows = result["rows"]
    columns = [
        "run",
        "case_number",
        "status",
        "output_present",
        "reference_pdf",
        "reference_pdf_match",
        "reference_hash_match",
        "field_status",
        "fact_status",
        "accuracy",
        "accuracy_rating",
        "tp",
        "fp",
        "fn",
        "precision",
        "recall",
        "f1",
        "reason",
    ]
    with (output_dir / "legal-evaluation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column) for column in columns} for row in rows)


def _template(paths: list[Path], destination: Path) -> None:
    cases: dict[int, dict[str, Any]] = {}
    for case_path in _iter_case_files(paths):
        try:
            record = _read_json(case_path)
            number = _case_number(record.get("case_number"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if number in cases:
            continue
        reference = record.get("reference_pdf")
        cases[number] = {
            "case_number": number,
            "reference_pdf": reference,
            "reference_sha256": record.get("reference_sha256"),
            "gold_facts": [],
            "adjudication": {
                "fields": {field: {"score": None, "note": ""} for field in FIELD_NAMES},
                "fact_verdicts": [],
                "false_positive_facts": [],
            },
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for number in sorted(cases):
            handle.write(json.dumps(cases[number], ensure_ascii=False) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, help="human-adjudicated gold JSON/JSONL")
    parser.add_argument("--outputs", type=Path, nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--init-gold", type=Path, help="write an annotation template and exit")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.init_gold:
        _template(args.outputs, args.init_gold)
        print(f"gold_template={args.init_gold}")
        return 0
    if not args.gold or not args.output_dir:
        raise SystemExit("--gold and --output-dir are required unless --init-gold is used")

    gold = _load_gold(args.gold)
    runs = _load_runs(args.outputs)
    if not runs:
        raise SystemExit("no case-*.json outputs found")
    rows: list[dict[str, Any]] = []
    aggregates: dict[str, Any] = {}
    for run_name, cases in sorted(runs.items()):
        run_rows = [
            _evaluate_case(run_name, number, cases.get(number), gold.get(number))
            for number in sorted(gold)
        ]
        rows.extend(run_rows)
        aggregates[run_name] = _aggregate(run_rows)
    result = {
        "schema_version": "decree-legal-evaluation.v1",
        "method": {
            "accuracy": "mean of eight field scores (1 correct, 0.5 partial, 0 incorrect/absent)",
            "facts": "atomic facts; TP correct, FP invented/incorrect, FN omitted",
            "precision": "TP/(TP+FP)",
            "recall": "TP/(TP+FN)",
            "f1": "harmonic mean of precision and recall",
            "ratings": dict((label, minimum) for minimum, label in THRESHOLDS),
            "legal_truth_source": "human adjudication in the gold manifest",
        },
        "caveats": [
            "Structural RAG metrics are not legal accuracy.",
            "Unannotated cases are NOT_CALCULABLE, not zero.",
            "Gold facts and field scores must be reviewed against the reference PDF.",
        ],
        "aggregates": aggregates,
        "rows": rows,
    }
    _write_outputs(args.output_dir, result)
    print(f"runs={len(aggregates)} rows={len(rows)} output_dir={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
