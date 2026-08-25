"""Inventory every benchmark run found in a local read-only snapshot.

The scanner deliberately treats the snapshot as opaque evidence.  It does not
infer missing configuration values from a run name; name-derived hints are kept
in a separate column for auditability.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


KNOWN_CONFIG_KEYS = (
    "embedding_model", "embedding_dimensions", "generator_model", "model",
    "rag_context", "ollama_context", "top_k", "candidate_pool",
    "minimum_score", "chunk_size", "chunk_overlap", "temperature", "seed",
    "reranker", "quantization", "requested_cases", "total_cases", "run_id",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def case_files(run_dir: Path) -> list[Path]:
    nested = sorted((run_dir / "cases").glob("case-*.json"))
    direct = sorted(run_dir.glob("case-*.json"))
    return nested or direct


def _find_number(name: str, patterns: Iterable[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def name_hints(name: str) -> dict[str, Any]:
    return {
        "model_size_hint": _find_number(name, (r"(?:^|-)s?(0\.6b|4b)(?:-|$)", r"(?:^|-)()06b(?:-|$)"))
        or ("0.6B" if "06b" in name.lower() else None),
        "rag_context_hint": _find_number(name, (r"rag(\d+)",)),
        "ollama_context_hint": _find_number(name, (r"ollama(\d+)",)),
        "smoke_hint": "smoke" in name.lower(),
    }


def _expected_cases(config: Mapping[str, Any], progress: Mapping[str, Any], run_dir: Path, available: int) -> int | None:
    for source in (config, progress):
        for key in ("requested_cases", "total_cases", "expected_cases", "case_count"):
            value = source.get(key)
            if isinstance(value, int) and value > 0:
                return value
    name = run_dir.name.lower()
    if "1000" in name:
        return 1000
    if "smoke" in name:
        return 20
    return available or None


def _flatten_known(config: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    def visit(value: Any) -> None:
        if not isinstance(value, Mapping):
            return
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in KNOWN_CONFIG_KEYS and not isinstance(item, (dict, list)):
                result[normalized] = item
            visit(item)

    visit(config)
    return result


def _join_counts(files: list[Path], gold_keys: set[tuple[str, str]] | None) -> tuple[int, int, int]:
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    invalid = 0
    for path in files:
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid += 1
            continue
        if not isinstance(case, Mapping):
            invalid += 1
            continue
        key = (str(case.get("reference_pdf", "")).lower(), str(case.get("reference_sha256", "")).lower())
        if key in seen:
            duplicates += 1
        seen.add(key)
        if gold_keys is not None and key not in gold_keys:
            invalid += 1
    return len(seen), duplicates, invalid


def discover(snapshot_root: Path, gold_path: Path | None = None) -> list[dict[str, Any]]:
    gold_keys: set[tuple[str, str]] | None = None
    if gold_path and gold_path.is_file():
        gold_keys = set()
        for line in gold_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, Mapping):
                gold_keys.add((str(item.get("reference_pdf", "")).lower(), str(item.get("reference_sha256", "")).lower()))

    rows: list[dict[str, Any]] = []
    seen_dirs: set[str] = set()
    candidate_dirs = {path for path in snapshot_root.rglob("cases") if path.is_dir()}
    candidate_dirs.update({path.parent for path in snapshot_root.rglob("case-*.json") if path.parent.name != "cases"})
    for candidate in sorted(candidate_dirs):
        if not candidate.is_dir():
            continue
        cases_dir = candidate if candidate.name == "cases" else candidate
        run_dir = cases_dir.parent if cases_dir.name == "cases" else cases_dir
        key = str(run_dir.resolve()).lower()
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        files = case_files(run_dir)
        config_path = run_dir / "configuration.json"
        if not config_path.is_file():
            config_path = run_dir / "config.json"
        progress = read_json(run_dir / "progress.json")
        config = read_json(config_path)
        available = len(files)
        expected = _expected_cases(config, progress, run_dir, available)
        run_status = str(progress.get("status") or config.get("status") or "")
        if not available or run_status in {"BLOCKED_EXTERNAL", "FAILED", "INVALID"}:
            integrity = "INVALID"
        elif expected and available >= expected:
            integrity = "FULL"
        else:
            integrity = "PARTIAL"
        unique, duplicates, bad_joins = _join_counts(files, gold_keys)
        if bad_joins and integrity == "FULL":
            integrity = "PARTIAL"
        hints = name_hints(run_dir.name)
        known = _flatten_known(config)
        config_hash = sha256_file(config_path) if config_path.is_file() else hashlib.sha256(b"{}").hexdigest()
        relative_locator = str(run_dir.resolve().relative_to(snapshot_root.resolve())).replace("\\", "/").lower()
        artifact_locator_hash = hashlib.sha256(relative_locator.encode("utf-8")).hexdigest()[:12]
        row: dict[str, Any] = {
            # A physical artifact ID must remain unique even when multiple
            # failed-attempt folders contain the same run name and config.
            "inventory_id": f"{run_dir.name}-{config_hash[:12]}-{artifact_locator_hash}",
            "artifact_locator_hash": artifact_locator_hash,
            "run_id": str(config.get("run_id") or run_dir.name),
            "source_run_dir": str(run_dir),
            "source_cases_dir": str(cases_dir),
            "source_root": str(snapshot_root),
            "integrity": integrity,
            "run_status": run_status or None,
            "available_cases": available,
            "expected_cases": expected,
            "unique_joins": unique,
            "duplicate_joins": duplicates,
            "invalid_gold_joins": bad_joins,
            "case_bytes": sum(p.stat().st_size for p in files if p.is_file()),
            "configuration_sha256": config_hash,
            "configuration_path": str(config_path) if config_path.is_file() else None,
            "configuration_json": config,
        }
        row.update({f"config_{key}": value for key, value in known.items()})
        row.update(hints)
        rows.append(row)
    return rows


def write_inventory(rows: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "runs_inventory.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    keys = sorted({key for row in rows for key in row if key != "configuration_json"})
    with (output_dir / "runs_inventory.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(row[key], ensure_ascii=False, sort_keys=True) if isinstance(row.get(key), (dict, list)) else row.get(key) for key in keys})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--gold", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark_v2/results/full-host-inventory"))
    args = parser.parse_args()
    rows = discover(args.snapshot_root, args.gold)
    write_inventory(rows, args.output_dir)
    counts = {status: sum(row["integrity"] == status for row in rows) for status in ("FULL", "PARTIAL", "INVALID")}
    print(json.dumps({"discovered": len(rows), **counts}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
