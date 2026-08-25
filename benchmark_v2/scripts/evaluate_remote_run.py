"""Evaluate the actual historical benchmark case files against PDF gold facts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_v2.evaluators.legal_core import evaluate_case


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}: line {line_number} is not an object")
            yield value


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _case_files(run_dir: Path) -> list[Path]:
    cases_dir = run_dir / "cases"
    files = sorted(cases_dir.glob("case-*.json")) if cases_dir.is_dir() else []
    return files or sorted(run_dir.glob("case-*.json"))


def evaluate_run(run_dir: Path, gold_path: Path, output_dir: Path, limit: int | None = None) -> dict[str, Any]:
    gold_by_join = {
        (str(item.get("reference_pdf", "")).lower(), str(item.get("reference_sha256", "")).lower()): item
        for item in _jsonl(gold_path)
    }
    files = _case_files(run_dir)
    if limit is not None:
        files = files[:limit]
    records: list[dict[str, Any]] = []
    join_errors: list[dict[str, Any]] = []
    for path in files:
        case = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(case, dict):
            join_errors.append({"file": path.name, "reason": "case_not_object"})
            continue
        key = (str(case.get("reference_pdf", "")).lower(), str(case.get("reference_sha256", "")).lower())
        gold = gold_by_join.get(key)
        if gold is None:
            join_errors.append({"file": path.name, "reason": "reference_pdf_or_sha256_not_in_gold", "join": key})
            continue
        record = evaluate_case(case, gold)
        record["case_file"] = path.name
        record["status"] = str(case.get("status") or "UNKNOWN")
        records.append(record)

    legal_pass = [bool(item["legal_pass"]) for item in records]
    source_statuses = {str(item["source_faithfulness"]["status"]): sum(1 for row in records if row["source_faithfulness"]["status"] == item["source_faithfulness"]["status"]) for item in records}
    summary = {
        "schema_version": "benchmark-v2-legal-core-1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "case_count": len(records),
        "requested_case_count": len(files),
        "join_errors": len(join_errors),
        "legal_pass_count": sum(legal_pass),
        "legal_pass_rate": sum(legal_pass) / len(legal_pass) if legal_pass else None,
        "prompt_coverage_rate": _mean([float(item["prompt_coverage"]["rate"]) for item in records if item["prompt_coverage"]["rate"] is not None]),
        "atomic_claim_recall": _mean([float(item["atomic_claims"]["recall"]) for item in records if item["atomic_claims"]["recall"] is not None]),
        "critical_contradiction_rate": sum(item["contradictions"]["critical_count"] > 0 for item in records) / len(records) if records else None,
        "critical_omission_rate": sum(item["omissions"]["critical_count"] > 0 for item in records) / len(records) if records else None,
        "unsupported_addition_rate": sum(item["unsupported_additions"]["critical_count"] > 0 for item in records) / len(records) if records else None,
        "source_faithfulness_status_counts": source_statuses,
        "retrieval_reconstruction_status_counts": source_statuses,
        "integrity": {"status": "FULL" if not join_errors and len(records) == len(files) else "PARTIAL", "join_errors": join_errors},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "decree_metrics.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records), encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "critical_errors.jsonl").write_text(
        "".join(json.dumps({"case_id": item["case_id"], "contradictions": item["contradictions"], "omissions": item["omissions"], "unsupported_additions": item["unsupported_additions"], "legal_pass_reasons": item["legal_pass_reasons"]}, ensure_ascii=False, sort_keys=True) + "\n" for item in records if not item["legal_pass"]), encoding="utf-8"
    )
    with (output_dir / "configuration_metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
        writer.writeheader()
        for key, value in summary.items():
            if isinstance(value, (str, int, float)) or value is None:
                writer.writerow({"metric": key, "value": value})
    manifest = {
        "schema_version": summary["schema_version"],
        "generated_at_utc": summary["generated_at_utc"],
        "input": {"run_dir": str(run_dir), "gold_path": str(gold_path), "gold_sha256": _sha256(gold_path)},
        "output": {"case_metrics_sha256": _sha256(output_dir / "decree_metrics.jsonl")},
        "limit": limit,
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    summary = evaluate_run(args.run_dir, args.gold, args.output_dir, args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["integrity"]["status"] == "FULL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
