"""Evaluate every discovered run with the frozen benchmark-v2 legal evaluator."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_v2.evaluators.legal_core import EVALUATOR_VERSION, RULES_VERSION, evaluate_case


EVALUATOR_PATH = ROOT / "benchmark_v2/evaluators/legal_core/evaluator.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def case_files(run_dir: Path) -> list[Path]:
    nested = sorted((run_dir / "cases").glob("case-*.json"))
    return nested or sorted(run_dir.glob("case-*.json"))


def sanitize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "run"


def load_gold(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in jsonl(path):
        key = (str(item.get("reference_pdf", "")).lower(), str(item.get("reference_sha256", "")).lower())
        result[key] = item
    return result


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def evaluate_one(row: dict[str, Any], gold: dict[tuple[str, str], dict[str, Any]], output_root: Path, evaluator_sha: str) -> dict[str, Any]:
    run_dir = Path(str(row["source_run_dir"]))
    run_slug = sanitize(str(row["inventory_id"]))
    output_dir = output_root / run_slug
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "metrics.jsonl"
    manifest_path = output_dir / "run_manifest.json"
    old_manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            old_manifest = value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            old_manifest = {}
    cached: dict[str, dict[str, Any]] = {}
    if old_manifest.get("evaluator_sha256") == evaluator_sha:
        for item in jsonl(metrics_path):
            fingerprint = item.get("case_fingerprint")
            if isinstance(fingerprint, str):
                cached[fingerprint] = item

    records: list[dict[str, Any]] = []
    join_errors: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0
    files = case_files(run_dir)
    for path in files:
        fingerprint = sha256_file(path)
        if fingerprint in cached:
            record = dict(cached[fingerprint])
            cache_hits += 1
        else:
            cache_misses += 1
            try:
                case = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                join_errors.append({"file": path.name, "reason": f"case_parse:{type(exc).__name__}"})
                continue
            if not isinstance(case, dict):
                join_errors.append({"file": path.name, "reason": "case_not_object"})
                continue
            key = (str(case.get("reference_pdf", "")).lower(), str(case.get("reference_sha256", "")).lower())
            reference = gold.get(key)
            if reference is None:
                join_errors.append({"file": path.name, "reason": "gold_join_missing", "join": key})
                continue
            record = evaluate_case(case, reference)
            record["status"] = str(case.get("status") or "UNKNOWN")
            record["case_file"] = path.name
            record["case_fingerprint"] = fingerprint
            record["total_ms"] = case.get("total_ms")
            record["retrieval_ms"] = case.get("retrieval_ms")
            record["generation_ms"] = case.get("generation_ms")
            record["run_id"] = row["run_id"]
        records.append(record)

    metrics_path.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records), encoding="utf-8")
    legal = [bool(item.get("legal_pass")) for item in records]
    def rate(predicate: Any) -> float | None:
        return sum(bool(predicate(item)) for item in records) / len(records) if records else None
    def avg(path: str) -> float | None:
        def nested(item: dict[str, Any]) -> Any:
            value: Any = item
            for part in path.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            return value
        values = [float(nested(item)) for item in records if isinstance(nested(item), (int, float))]
        return mean(values) if values else None

    source_status = Counter(str(item.get("source_faithfulness", {}).get("status", "UNKNOWN")) for item in records)
    retrieval_status = Counter(str(item.get("retrieval", {}).get("status", "UNKNOWN")) for item in records)
    latency = [float(item["total_ms"]) for item in records if isinstance(item.get("total_ms"), (int, float))]
    summary: dict[str, Any] = {
        "schema_version": "benchmark-v2-all-runs-summary-1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": row["run_id"],
        "artifact_id": row["inventory_id"],
        "integrity": row["integrity"] if not join_errors else "PARTIAL",
        "case_count": len(records),
        "requested_case_count": len(files),
        "expected_case_count": row.get("expected_cases"),
        "join_errors": len(join_errors),
        "legal_pass_count": sum(legal),
        "legal_pass_rate": mean(legal) if legal else None,
        "prompt_coverage_rate": avg("prompt_coverage.rate"),
        "atomic_claim_recall": avg("atomic_claims.recall"),
        "critical_fields_correct_rate": rate(lambda item: item.get("critical_fields", {}).get("all_correct") is True),
        "critical_contradiction_rate": rate(lambda item: item.get("contradictions", {}).get("critical_count", 0) > 0),
        "critical_omission_rate": rate(lambda item: item.get("omissions", {}).get("critical_count", 0) > 0),
        "unsupported_addition_rate": rate(lambda item: item.get("unsupported_additions", {}).get("critical_count", 0) > 0),
        "citation_traceability_rate": avg("source_faithfulness.citation_traceability"),
        "source_faithfulness_status_counts": dict(source_status),
        "retrieval_reconstruction_status_counts": dict(retrieval_status),
        "latency_total_ms_mean": mean(latency) if latency else None,
        "latency_total_ms_p50": percentile(latency, 0.50),
        "latency_total_ms_p95": percentile(latency, 0.95),
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "configuration_sha256": row.get("configuration_sha256"),
        "configuration": row.get("configuration_json", {}),
        "join_error_details": join_errors[:100],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "critical_errors.jsonl").write_text("".join(json.dumps({"case_id": item.get("case_id"), "contradictions": item.get("contradictions"), "omissions": item.get("omissions"), "unsupported_additions": item.get("unsupported_additions"), "legal_pass_reasons": item.get("legal_pass_reasons")}, ensure_ascii=False, sort_keys=True) + "\n" for item in records if not item.get("legal_pass")), encoding="utf-8")
    manifest = {
        "schema_version": "benchmark-v2-all-runs-manifest-1",
        "evaluator_sha256": evaluator_sha,
        "evaluator_path": str(EVALUATOR_PATH),
        "gold_sha256": None,
        "source_run_dir": str(run_dir),
        "artifact_id": row["inventory_id"],
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "metrics_sha256": sha256_file(metrics_path),
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def write_aggregates(summaries: list[dict[str, Any]], output_root: Path) -> None:
    fields = sorted({key for row in summaries for key, value in row.items() if not isinstance(value, (dict, list))})
    with (output_root / "configuration_metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in summaries:
            writer.writerow({key: row.get(key) for key in fields})
    for status in ("FULL", "PARTIAL", "INVALID"):
        selected = [row for row in summaries if row.get("integrity") == status]
        with (output_root / f"configuration_metrics_{status.lower()}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows({key: row.get(key) for key in fields} for row in selected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("benchmark_v2/results/all-runs-20260825"))
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    rows = json.loads((args.inventory / "runs_inventory.json").read_text(encoding="utf-8"))
    evaluator_sha = sha256_file(EVALUATOR_PATH)
    gold = load_gold(args.gold)
    summaries: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        print(json.dumps({"discovered": len(rows), "current": index, "run_id": row.get("run_id"), "integrity": row.get("integrity")}, ensure_ascii=False), flush=True)
        if row.get("integrity") == "INVALID" and not case_files(Path(str(row["source_run_dir"]))):
            summary = {"run_id": row["run_id"], "artifact_id": row["inventory_id"], "integrity": "INVALID", "case_count": 0, "join_errors": 0}
        else:
            summary = evaluate_one(row, gold, args.output_root, evaluator_sha)
        summaries.append(summary)
    write_aggregates(summaries, args.output_root)
    (args.output_root / "evaluator_manifest.json").write_text(json.dumps({"evaluator_sha256": evaluator_sha, "evaluator_path": str(EVALUATOR_PATH), "evaluator_version": EVALUATOR_VERSION, "rules_version": RULES_VERSION, "gold_sha256": sha256_file(args.gold), "judge_model": None, "bootstrap_seed": 20260825}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"discovered": len(rows), "evaluated": sum(int(row.get("case_count", 0) or 0) for row in summaries), "full": sum(row.get("integrity") == "FULL" for row in summaries), "partial": sum(row.get("integrity") == "PARTIAL" for row in summaries), "invalid": sum(row.get("integrity") == "INVALID" for row in summaries)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
