"""Reconcile physical artifacts into logical benchmark experiments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


EVALUATOR = Path(__file__).resolve().parents[2] / "benchmark_v2/evaluators/legal_core/evaluator.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def case_files(run_dir: Path) -> list[Path]:
    nested = sorted((run_dir / "cases").glob("case-*.json"))
    return nested or sorted(run_dir.glob("case-*.json"))


def config_payload(row: dict[str, Any]) -> dict[str, Any]:
    config = row.get("configuration_json") or {}
    if not isinstance(config, dict):
        config = {}
    stripped = {key: value for key, value in config.items() if str(key).lower() not in {"run_id", "status", "started_at", "finished_at", "generated_at", "timestamp"}}
    name = Path(str(row.get("source_run_dir", ""))).name.lower()
    # These are explicit experiment-family tokens, not invented numeric values.
    family = name
    for token in ("-smoke", "-recovery-1", "-recovery-2", "-recovery", "-auto-resume", "-final", "-diagnostic", "-blocked-warmup", "-blocked-timeout30", "-invalid-residency", "-timeout-fix", "-residency-smoke", "-residency-smoke-failed-network", "-pre-explicit-keepalive"):
        family = family.replace(token, "")
    family = re.sub(r"-202608\d+T?\d*Z?", "", family)
    stripped["experiment_family_token"] = family
    stripped["model_size_hint"] = row.get("model_size_hint")
    stripped["rag_context_hint"] = row.get("rag_context_hint")
    stripped["ollama_context_hint"] = row.get("ollama_context_hint")
    return stripped


def hashes(row: dict[str, Any]) -> tuple[str, str, int]:
    files = case_files(Path(str(row["source_run_dir"])))
    case_keys: list[dict[str, Any]] = []
    output_values: list[dict[str, Any]] = []
    for path in files:
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(case, dict):
            continue
        case_keys.append({"reference_pdf": str(case.get("reference_pdf", "")).lower(), "reference_sha256": str(case.get("reference_sha256", "")).lower(), "case_number": case.get("case_number")})
        output_values.append({"reference_pdf": str(case.get("reference_pdf", "")).lower(), "reference_sha256": str(case.get("reference_sha256", "")).lower(), "output": case.get("output"), "status": case.get("status")})
    case_digest = hashlib.sha256(canonical(sorted(case_keys, key=canonical)).encode("utf-8")).hexdigest()
    output_digest = hashlib.sha256(canonical(sorted(output_values, key=canonical)).encode("utf-8")).hexdigest()
    return case_digest, output_digest, len(case_keys)


def classify(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evaluator_hash = sha256_file(EVALUATOR)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        row["artifact_id"] = row.get("inventory_id")
        payload = config_payload(row)
        row["config_hash"] = hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
        row["logical_run_id"] = "logical-" + row["config_hash"][:12]
        case_hash, output_hash, case_count = hashes(row)
        row["case_set_hash"] = case_hash
        row["output_hash"] = output_hash
        row["case_set_count"] = case_count
        row["evaluator_hash"] = evaluator_hash
        groups[row["logical_run_id"]].append(row)

    for logical_rows in groups.values():
        full = [row for row in logical_rows if row.get("integrity") == "FULL" and int(row.get("expected_cases") or 0) == 1000]
        non_archive = [row for row in full if "/archive/" not in str(row.get("source_run_dir", "")).replace("\\", "/").lower()]
        primary_pool = [row for row in non_archive if not re.search(r"recovery|resume|attempt", str(row.get("source_run_dir", "")), re.IGNORECASE)] or non_archive
        primary = min(primary_pool, key=lambda row: str(row.get("source_run_dir", ""))) if primary_pool else None
        exact_primary_keys = {(row.get("config_hash"), row.get("case_set_hash"), row.get("output_hash")) for row in full}
        for row in logical_rows:
            path = str(row.get("source_run_dir", "")).replace("\\", "/").lower()
            name = Path(path).name
            diagnostic_hint = any(token in name for token in ("debug", "diagnostic", "blocked", "timeout", "invalid-residency", "errors")) or "failed-attempts" in path
            if row.get("integrity") == "INVALID":
                classification = "INVALID"
            elif row.get("integrity") == "PARTIAL":
                classification = "PARTIAL"
            elif diagnostic_hint and "smoke" not in name and int(row.get("expected_cases") or 0) != 1000:
                classification = "DIAGNOSTIC"
            elif "smoke" in name:
                classification = "SMOKE"
            elif row in full and primary is row:
                classification = "PRIMARY_FULL_1000"
            elif row.get("integrity") == "FULL" and int(row.get("expected_cases") or 0) == 1000:
                key = (row.get("config_hash"), row.get("case_set_hash"), row.get("output_hash"))
                if key in exact_primary_keys and "/archive/" in path:
                    classification = "ARCHIVE_DUPLICATE"
                elif re.search(r"recovery|resume|attempt", path, re.IGNORECASE):
                    classification = "RECOVERED_COPY"
                else:
                    classification = "REPLICATE_FULL_1000"
            elif int(row.get("expected_cases") or 0) < 1000:
                classification = "PARTIAL"
            else:
                classification = "DIAGNOSTIC"
            row["classification"] = classification
            row["is_primary_for_inference"] = classification == "PRIMARY_FULL_1000"
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = classify(json.loads((args.inventory / "runs_inventory.json").read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["artifact_id", "logical_run_id", "run_id", "config_hash", "case_set_hash", "output_hash", "evaluator_hash", "classification", "is_primary_for_inference", "integrity", "available_cases", "expected_cases", "source_run_dir", "configuration_sha256", "model_size_hint", "rag_context_hint", "ollama_context_hint", "config_top_k", "config_candidate_pool", "config_minimum_score", "config_temperature", "config_seed"]
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})
    (args.output.with_suffix(".json")).write_text(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = {label: sum(row["classification"] == label for row in rows) for label in ("PRIMARY_FULL_1000", "REPLICATE_FULL_1000", "SMOKE", "DIAGNOSTIC", "PARTIAL", "ARCHIVE_DUPLICATE", "RECOVERED_COPY", "INVALID")}
    print(json.dumps({"artifacts": len(rows), **counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
