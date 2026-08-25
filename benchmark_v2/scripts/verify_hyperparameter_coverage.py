"""Verify host-folder coverage and canonical hyperparameter combinations.

This is an inventory-only check. It never evaluates a case and therefore does
not rerun the benchmark. The remote run catalog is used to normalize the
effective configuration of smoke, failed-attempt, diagnostic, and archived
folders back to their canonical C01--C19 configuration.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REMOTE_ROOT_DEFAULT = "/home/root-labia/legal-AI-infraestructure/backups/benchmark-results"
NOT_RECORDED = "NOT_RECORDED"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_hash(signature: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(signature).encode("utf-8")).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fields} for row in rows)


def relative_run_path(row: dict[str, Any]) -> str:
    source = Path(str(row["source_run_dir"]))
    root = Path(str(row["source_root"]))
    return str(source.resolve().relative_to(root.resolve())).replace("\\", "/")


def remove_attempt_path(value: str) -> str:
    match = re.search(r"/failed-attempts/[^/]+$", value)
    return value[: match.start()] if match else value


def strip_smoke(value: str) -> str:
    return value.split("-smoke", 1)[0] if "-smoke" in value else value


def catalog_match(relative_path: str, catalog_by_path: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    base = remove_attempt_path(relative_path)
    if base in catalog_by_path:
        return catalog_by_path[base]
    name = Path(base).name
    stripped_name = strip_smoke(name)
    candidates = [
        "/".join((*Path(base).parts[:-1], stripped_name)),
        stripped_name,
    ]
    for candidate in candidates:
        if candidate in catalog_by_path:
            return catalog_by_path[candidate]
    # Historical diagnostic names were not always derived from the canonical
    # run name, but their path still identifies the experiment family.
    family_prefixes = (
        ("benchmark-1000-8192-v3", "benchmark-1000-8192-v3"),
        ("benchmark-1000-4096-v", "benchmark-1000-4096-v2"),
        ("benchmark-1000-06b-balanced", "benchmark-1000-06b-balanced"),
        ("benchmark-1000-06b-precision", "benchmark-1000-06b-precision"),
        ("benchmark-1000-06b-recall", "benchmark-1000-06b-recall"),
        ("benchmark-1000-06b-diverse", "benchmark-1000-06b-diverse"),
        ("benchmark-1000-06b-compact", "benchmark-1000-06b-compact"),
    )
    for prefix, canonical_name in family_prefixes:
        if prefix in name:
            for path, entry in catalog_by_path.items():
                if Path(path).name == canonical_name:
                    return entry
    if any(token in name for token in ("debug-case7", "errors", "pre-resume", "resume-residency")):
        return next((entry for path, entry in catalog_by_path.items() if Path(path).name == "benchmark-1000-4096-v2"), None)
    for path, entry in catalog_by_path.items():
        if Path(path).name == stripped_name:
            return entry
    return None


def signature(entry: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": catalog.get("generation_model", NOT_RECORDED),
        "embedding_model": entry.get("embedding_model", NOT_RECORDED),
        "embedding_context": entry.get("embedding_context", NOT_RECORDED),
        "embedding_dimensions": entry.get("embedding_dimensions", NOT_RECORDED),
        "rag_context": entry.get("rag_context", NOT_RECORDED),
        "ollama_context": entry.get("ollama_context", NOT_RECORDED),
        "chunk_size": entry.get("chunk_size", NOT_RECORDED),
        "chunk_overlap": entry.get("chunk_overlap", NOT_RECORDED),
        "top_k": entry.get("top_k", NOT_RECORDED),
        "pool": entry.get("candidate_pool", NOT_RECORDED),
        "threshold": entry.get("minimum_score", NOT_RECORDED),
        "temperature": entry.get("temperature", NOT_RECORDED),
        "seed": entry.get("seed", NOT_RECORDED),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--run-catalog", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("benchmark_v2/results/full-host-inventory/hyperparameter_coverage.csv"))
    parser.add_argument("--remote-root", default=REMOTE_ROOT_DEFAULT)
    parser.add_argument("--remote-folder-count", type=int, required=True)
    parser.add_argument("--remote-folder-digest", required=True)
    args = parser.parse_args()

    inventory = json.loads((args.inventory / "runs_inventory.json").read_text(encoding="utf-8"))
    reconciliation = json.loads(args.reconciliation.read_text(encoding="utf-8"))
    reconciliation_by_artifact = {str(row["artifact_id"]): row for row in reconciliation}
    catalog = json.loads(args.run_catalog.read_text(encoding="utf-8"))
    catalog_by_path = {str(entry["path"]): entry for entry in catalog["runs"]}

    local_paths = sorted(relative_run_path(row) for row in inventory)
    local_digest = hashlib.sha256(("".join("./" + path + "\n" for path in local_paths)).encode("utf-8")).hexdigest()
    remote_folder_count = args.remote_folder_count
    remote_digest = args.remote_folder_digest

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    signatures_by_hash: dict[str, set[str]] = defaultdict(set)
    unmapped: list[dict[str, Any]] = []
    artifact_rows: list[dict[str, Any]] = []
    for row in inventory:
        artifact_id = str(row["inventory_id"])
        relative = relative_run_path(row)
        entry = catalog_match(relative, catalog_by_path)
        if entry is None:
            unmapped.append({"artifact_id": artifact_id, "source_path": relative})
            continue
        sig = signature(entry, catalog)
        hp_hash = config_hash(sig)
        rec = reconciliation_by_artifact[artifact_id]
        artifact = {
            "artifact_id": artifact_id,
            "relative_path": relative,
            "source_path_remote": f"{args.remote_root}/{relative}",
            "classification": rec.get("classification"),
            "available_cases": row.get("available_cases"),
            "expected_cases": row.get("expected_cases"),
            "integrity": row.get("integrity"),
            "config_hash": hp_hash,
            "logical_run_id": "logical-" + hp_hash[:12],
            "output_hash": rec.get("output_hash"),
            "catalog_run": entry.get("case_id"),
            "catalog_label": entry.get("label"),
            "catalog_path": entry.get("path"),
            "signature": sig,
        }
        grouped[hp_hash].append(artifact)
        signatures_by_hash[hp_hash].add(canonical(sig))
        artifact_rows.append(artifact)

    coverage: list[dict[str, Any]] = []
    primary_ids = {str(row["artifact_id"]) for row in reconciliation if row.get("classification") == "PRIMARY_FULL_1000"}
    evaluated_ids = set()
    for path in (args.results_root / "stats" / "primary_configuration_metrics.csv",):
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as handle:
                evaluated_ids.update(str(row["artifact_id"]) for row in csv.DictReader(handle) if row.get("artifact_id"))
    primary_table: list[dict[str, Any]] = []
    for hp_hash, artifacts in grouped.items():
        sig = artifacts[0]["signature"]
        catalog_entry = next(entry for entry in catalog["runs"] if entry.get("case_id") == artifacts[0]["catalog_run"])
        valid_full = [item for item in artifacts if item["integrity"] == "FULL" and int(item.get("expected_cases") or 0) == 1000 and int(item.get("available_cases") or 0) >= 1000 and not int(next(row for row in inventory if row["inventory_id"] == item["artifact_id"]).get("invalid_gold_joins") or 0)]
        primary = [item for item in artifacts if item["artifact_id"] in primary_ids]
        class_counts = Counter(str(item["classification"]) for item in artifacts)
        full_output_hashes = {str(item.get("output_hash")) for item in valid_full if item.get("output_hash")}
        replicate_candidate = len(valid_full) > 1 and len(full_output_hashes) > 1
        classification = "PRIMARY_FULL_1000" if primary else "PARTIAL" if any(item["classification"] == "PARTIAL" for item in artifacts) else max(class_counts, key=class_counts.get)
        coverage.append({
            "config_hash": hp_hash,
            "logical_run_id": "logical-" + hp_hash[:12],
            "run": catalog_entry.get("case_id"),
            "runs": ";".join(sorted({str(item["catalog_run"]) for item in artifacts})),
            "label": catalog_entry.get("label"),
            "source_path_remote": f"{args.remote_root}/{catalog_entry.get('path')}",
            "artifact_source_paths_remote": ";".join(sorted(item["source_path_remote"] for item in artifacts)),
            "classification": classification,
            "artifact_count": len(artifacts),
            "available_cases": max(int(item.get("available_cases") or 0) for item in artifacts),
            "full_1000_artifact_count": len(valid_full),
            "full_1000_evaluated": bool(primary) and all(item["artifact_id"] in evaluated_ids for item in primary),
            "full_1000_evaluated_artifact_count": sum(item["artifact_id"] in evaluated_ids for item in valid_full),
            "full_output_hash_count": len(full_output_hashes),
            "replicate_candidate_unseeded": replicate_candidate,
            "artifact_classifications": ";".join(f"{key}={value}" for key, value in sorted(class_counts.items())),
            **sig,
        })
        for item in primary:
            primary_table.append({
                "run": item["catalog_run"],
                "label": item["catalog_label"],
                "config_hash": hp_hash,
                "logical_run_id": "logical-" + hp_hash[:12],
                "source_path_remote": item["source_path_remote"],
                "classification": item["classification"],
                "available_cases": item["available_cases"],
                "evaluated": item["artifact_id"] in evaluated_ids,
                **sig,
            })
    coverage.sort(key=lambda row: str(row["run"]))
    primary_table.sort(key=lambda row: str(row["run"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output, coverage)
    mapping_path = args.output.with_name("hyperparameter_artifact_mapping.csv")
    write_csv(mapping_path, [{key: item[key] for key in ("artifact_id", "relative_path", "source_path_remote", "classification", "available_cases", "config_hash", "logical_run_id", "catalog_run", "catalog_label", "output_hash")} for item in artifact_rows])

    primary_coverage = [row for row in coverage if row["classification"] == "PRIMARY_FULL_1000"]
    # Recompute from the grouped artifacts to avoid relying on classification.
    valid_full_groups = {
        hp_hash
        for hp_hash, artifacts in grouped.items()
        if any(item["integrity"] == "FULL" and int(item.get("expected_cases") or 0) == 1000 and int(item.get("available_cases") or 0) >= 1000 for item in artifacts)
    }
    misclassified = [item for item in artifact_rows if item["integrity"] == "FULL" and int(item.get("expected_cases") or 0) == 1000 and int(item.get("available_cases") or 0) >= 1000 and item["classification"] != "PRIMARY_FULL_1000"]
    report = {
        "remote_folders_detected": remote_folder_count,
        "artifacts_inventoried": len(inventory),
        "unique_artifact_ids": len({row["inventory_id"] for row in inventory}),
        "unique_hyperparameter_configs": len(coverage),
        "full_1000_unique_hyperparameter_configs": len(valid_full_groups),
        "full_1000_runs": len(primary_ids),
        "full_1000_evaluated_runs": len(primary_ids & evaluated_ids),
        "full_1000_evaluated_ratio": f"{len(primary_ids & evaluated_ids)}/{len(primary_ids)}",
        "full_1000_unique_evaluated_ratio": f"{len(primary_coverage)}/{len(valid_full_groups)}",
        "omitted_full_configs": sorted(valid_full_groups - {row["config_hash"] for row in primary_coverage}),
        "unmapped_artifacts": unmapped,
        "misclassified_valid_full_artifacts": misclassified,
        "local_folder_count": len(local_paths),
        "local_folder_digest": local_digest,
        "remote_folder_digest": remote_digest,
        "remote_local_folder_digest_match": remote_folder_count == len(local_paths) and remote_digest == local_digest,
        "folders_not_reconciled": len(unmapped) + (0 if remote_folder_count == len(local_paths) and remote_digest == local_digest else abs(remote_folder_count - len(local_paths))),
        "classification_counts": dict(Counter(str(row["classification"]) for row in reconciliation)),
        "not_recorded_fields": ["embedding_context", "chunk_size", "chunk_overlap", "temperature", "seed"],
        "source_of_hyperparameters": "remote run-catalog.json reconciled to physical artifact paths",
        "same_hyperparameters_share_config_hash": True,
        "config_hash_signature_collision_count": sum(len(values) > 1 for values in signatures_by_hash.values()),
        "replicate_candidate_configs": [row["run"] for row in coverage if row.get("replicate_candidate_unseeded")],
        "benchmark_recalculation_required": bool(unmapped or misclassified or (valid_full_groups - {row["config_hash"] for row in primary_coverage})),
        "coverage_status": "COVERAGE_COMPLETE" if not unmapped and not misclassified and not (valid_full_groups - {row["config_hash"] for row in primary_coverage}) else "COVERAGE_INCOMPLETE",
    }
    report_path = args.output.with_name("hyperparameter_coverage_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    primary_path = args.output.with_name("hyperparameter_coverage_primary_17.csv")
    write_csv(primary_path, primary_table)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["coverage_status"] == "COVERAGE_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
