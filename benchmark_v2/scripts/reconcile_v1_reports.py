#!/usr/bin/env python3
"""Reconcile V1 historical benchmark artifacts with raw 1000-case runs.

Read-only audit: it never modifies repository benchmark artifacts
(``docs/benchmarks/``, ``apps/api/artifacts/``) nor the remote snapshot of raw
runs. The only file it produces is its own JSON report, which must live under
``benchmark_v2/`` (or outside both input roots).

Reconciled sources:

* ``docs/benchmarks/holdout-1000/run-catalog.json`` - V1 run catalog
  (``legal-ai-benchmark-run-catalog.v1``).
* ``docs/benchmarks/holdout-1000/results/benchmark-summary.json`` and
  ``benchmark-summary.csv`` - consolidated historical evaluation.
* ``docs/benchmarks/holdout-1000/inputs-manifest.json`` - frozen prompt
  manifest of the holdout cases.
* ``apps/api/artifacts/benchmarks/004.json`` - V1 performance report
  (``004-benchmark-v1``) plus its dataset fixture digest.
* Remote snapshot with ``manifest.csv``, ``pdf-gold-facts.auto.jsonl`` and one
  folder per raw run containing ``cases/case-NNNN.json``, ``experiment.yml``,
  ``configuration.json``, ``progress.json`` and ``summary.csv``.

Every disagreement becomes a finding; nothing is silently coerced. Exit code
is ``2`` when any BLOCK finding exists, ``0`` otherwise (WARN does not fail).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "benchmark-v2-reconciliation.v1"
TASK_ID = "task_20d7b2a4cef3"

CATALOG_SCHEMA = "legal-ai-benchmark-run-catalog.v1"
CONSOLIDATED_SCHEMA = "decree-factual-fidelity.v2"
PERF_V1_SCHEMA = "004-benchmark-v1"
PROMPT_VERSION = "holdout-prompt-v2"

FROZEN_PROMPT_MANIFEST_SHA256 = (
    "26b72644e00ee44aff6fcb492aed616d6d4a438b44ed6d5abed3c5541697a930"
)
FROZEN_REFERENCE_CACHE_SHA256 = (
    "6b477c37c21219fdf45e1f1946e59a609a232b7872825d1dc71c3d8575f96d61"
)

EXPECTED_CASES = 1000
MAX_DETAIL_EXAMPLES = 20
LATENCY_TOLERANCE_MS = 1.0
FLOAT_TOLERANCE = 1e-9

MANIFEST_FIELDS = (
    "case_id",
    "prompt_file",
    "source_pdf",
    "source_sha256",
    "pages",
    "extracted_chars",
    "target_identifier_redacted",
    "organization",
    "objective",
    "facts",
    "operative_requirements",
    "quality_status",
)

CATALOG_PARAM_KEYS = (
    "embedding_model",
    "embedding_dimensions",
    "rag_context",
    "ollama_context",
    "top_k",
    "candidate_pool",
    "minimum_score",
)

EXPERIMENT_TO_CATALOG = {
    "embedding_model": "embedding_model",
    "dimensions": "embedding_dimensions",
    "rag_context_tokens": "rag_context",
    "ollama_context_length": "ollama_context",
    "top_k": "top_k",
    "minimum_score": "minimum_score",
}

SUMMARY_INT_COLUMNS = (
    "expected_cases",
    "outputs_found",
    "succeeded",
    "failed",
    "missing",
    "invalid_reference_joins",
)

SUMMARY_FLOAT_COLUMNS = ("coverage", "success_rate")

INFO = "INFO"
WARN = "WARN"
BLOCK = "BLOCK"


@dataclass
class Finding:
    check: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class ReconciliationReport:
    findings: list[Finding] = field(default_factory=list)

    def add(
        self,
        check: str,
        severity: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> Finding:
        finding = Finding(check, severity, message, details or {})
        self.findings.append(finding)
        return finding

    @property
    def blocks(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == BLOCK]

    @property
    def warns(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARN]

    def status(self) -> str:
        if self.blocks:
            return "FAIL"
        if self.warns:
            return "WARN"
        return "PASS"

    def counts(self) -> dict[str, int]:
        return {
            "info": sum(1 for f in self.findings if f.severity == INFO),
            "warn": len(self.warns),
            "block": len(self.blocks),
        }

    def to_list(self) -> list[dict[str, Any]]:
        return [finding.to_dict() for finding in self.findings]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_json_or_none(path: Path) -> tuple[Any | None, str | None]:
    try:
        return read_json(path), None
    except (OSError, ValueError) as error:
        return None, f"{type(error).__name__}: {error}"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", "" if value is None else str(value))
    return re.sub(r"\s+", " ", text).strip()


def _cap(examples: list[str]) -> list[str]:
    kept = examples[:MAX_DETAIL_EXAMPLES]
    omitted = len(examples) - len(kept)
    if omitted > 0:
        kept.append(f"... (+{omitted} more)")
    return kept


def discover_run_dirs(remote_dir: Path) -> list[Path]:
    runs = []
    for entry in sorted(remote_dir.iterdir()):
        if entry.is_dir() and any((entry / "cases").glob("case-*.json")):
            runs.append(entry)
    return runs


def catalog_entry_for_folder(
    catalog_runs: list[dict[str, Any]], folder: str
) -> dict[str, Any] | None:
    for entry in catalog_runs:
        if Path(str(entry.get("path", ""))).name == folder:
            return entry
    return None


def summary_entry_for_case(
    summary: dict[str, Any], case_id: str
) -> dict[str, Any] | None:
    for entry in summary.get("summaries", []):
        if entry.get("case_id") == case_id:
            return entry
    return None


def observed_median_ms(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 0:
        return (ordered[middle - 1] + ordered[middle]) / 2
    return float(ordered[middle])


def values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(
            float(left), float(right), rel_tol=FLOAT_TOLERANCE, abs_tol=1e-12
        )
    return left == right

# ---------------------------------------------------------------------------
# Frozen inputs identity
# ---------------------------------------------------------------------------


def check_frozen_inputs(
    report: ReconciliationReport,
    inputs_manifest: Path,
    reference_cache: Path,
    expected_prompt_sha: str,
    expected_cache_sha: str,
) -> None:
    actual_prompt_sha = sha256_file(inputs_manifest)
    if actual_prompt_sha != expected_prompt_sha:
        report.add(
            "inputs-manifest-digest",
            BLOCK,
            "Prompt manifest digest does not match the frozen documented value.",
            {
                "path": str(inputs_manifest),
                "expected": expected_prompt_sha,
                "actual": actual_prompt_sha,
            },
        )
    actual_cache_sha = sha256_file(reference_cache)
    if actual_cache_sha != expected_cache_sha:
        report.add(
            "reference-cache-digest",
            BLOCK,
            "Reference factual cache digest does not match the frozen documented value.",
            {
                "path": str(reference_cache),
                "expected": expected_cache_sha,
                "actual": actual_cache_sha,
            },
        )


def check_consolidated_frozen_digests(
    summary: dict[str, Any],
    actual_prompt_sha: str,
    actual_cache_sha: str,
    report: ReconciliationReport,
) -> None:
    quality = summary.get("data_quality", {})
    recorded = {
        "prompt_manifest_sha256": quality.get("prompt_manifest_sha256"),
        "reference_cache_sha256": quality.get("reference_cache_sha256"),
    }
    frozen = {
        "prompt_manifest_sha256": FROZEN_PROMPT_MANIFEST_SHA256,
        "reference_cache_sha256": FROZEN_REFERENCE_CACHE_SHA256,
    }
    if recorded != frozen:
        report.add(
            "consolidated-summary-frozen-digests",
            BLOCK,
            "Consolidated summary records digests that differ from the frozen values.",
            {"recorded": recorded, "frozen": frozen},
        )
    if (
        quality.get("prompt_manifest_sha256") not in (None, actual_prompt_sha)
        or quality.get("reference_cache_sha256") not in (None, actual_cache_sha)
    ):
        report.add(
            "consolidated-summary-actual-digests",
            BLOCK,
            "Actual input digests differ from those recorded in the consolidated summary.",
            {
                "actual_prompt_manifest_sha256": actual_prompt_sha,
                "actual_reference_cache_sha256": actual_cache_sha,
                "recorded": recorded,
            },
        )


# ---------------------------------------------------------------------------
# Run catalog integrity
# ---------------------------------------------------------------------------


def check_catalog(
    catalog: dict[str, Any], report: ReconciliationReport
) -> list[dict[str, Any]]:
    runs = catalog.get("runs")
    if catalog.get("schema_version") != CATALOG_SCHEMA:
        report.add(
            "catalog-schema",
            BLOCK,
            "Run catalog schema version is not the V1 contract.",
            {"expected": CATALOG_SCHEMA, "actual": catalog.get("schema_version")},
        )
    if not isinstance(runs, list) or not runs:
        report.add(
            "catalog-integrity",
            BLOCK,
            "Run catalog has no runs.",
            {"schema_version": catalog.get("schema_version")},
        )
        return []
    if catalog.get("prompt_version") != PROMPT_VERSION:
        report.add(
            "catalog-prompt-version",
            WARN,
            "Run catalog prompt version differs from the frozen prompt set.",
            {"actual": catalog.get("prompt_version")},
        )

    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    duplicates: list[str] = []
    for entry in runs:
        case_id = str(entry.get("case_id", ""))
        path = str(entry.get("path", ""))
        if case_id in seen_ids:
            duplicates.append(f"case_id={case_id}")
        seen_ids.add(case_id)
        if path in seen_paths:
            duplicates.append(f"path={path}")
        seen_paths.add(path)
    if duplicates:
        report.add(
            "catalog-uniqueness",
            BLOCK,
            "Run catalog has duplicated case identifiers or paths.",
            {"duplicates": duplicates},
        )

    if catalog.get("expected_cases") != EXPECTED_CASES:
        report.add(
            "catalog-expected-cases",
            BLOCK,
            "Run catalog does not describe 1000 cases per run.",
            {"expected": EXPECTED_CASES, "actual": catalog.get("expected_cases")},
        )
    return runs


# ---------------------------------------------------------------------------
# Repo manifest vs remote manifest equivalence
# ---------------------------------------------------------------------------


def check_manifest_equivalence(
    records: list[dict[str, Any]],
    rows: list[dict[str, str]],
    report: ReconciliationReport,
) -> None:
    if len(records) != len(rows):
        report.add(
            "manifest-equivalence",
            BLOCK,
            "Repo prompt manifest and remote manifest.csv disagree on case count.",
            {"repo_records": len(records), "remote_rows": len(rows)},
        )
    mismatches: list[str] = []
    for index in range(min(len(records), len(rows))):
        record = records[index]
        row = rows[index]
        for field_name in MANIFEST_FIELDS:
            left = normalize_text(record.get(field_name))
            right = normalize_text(row.get(field_name))
            if left != right:
                mismatches.append(
                    f"row {index + 1} field {field_name}: repo={left!r} remote={right!r}"
                )
    if mismatches:
        report.add(
            "manifest-equivalence",
            BLOCK,
            "Repo prompt manifest and remote manifest.csv disagree on field values.",
            {"mismatch_count": len(mismatches), "examples": _cap(mismatches)},
        )


# ---------------------------------------------------------------------------
# Reference cache coverage
# ---------------------------------------------------------------------------


def load_reference_cache(
    path: Path, report: ReconciliationReport
) -> dict[tuple[str, str], dict[str, Any]]:
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    duplicates: list[str] = []
    parse_errors: list[str] = []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError as error:
            parse_errors.append(f"line {line_number}: {error}")
            continue
        key = (str(payload.get("reference_pdf")), str(payload.get("reference_sha256")))
        if key in entries:
            duplicates.append(key[0])
        entries[key] = payload
    if parse_errors:
        report.add(
            "reference-cache-parse",
            BLOCK,
            "Reference cache contains unparseable lines.",
            {"errors": _cap(parse_errors)},
        )
    if duplicates:
        report.add(
            "reference-cache-duplicates",
            BLOCK,
            "Reference cache contains duplicated PDF keys.",
            {"duplicates": _cap(duplicates)},
        )
    return entries


def check_reference_coverage(
    rows: list[dict[str, str]],
    entries: dict[tuple[str, str], dict[str, Any]],
    report: ReconciliationReport,
) -> None:
    expected_keys = {
        (normalize_text(row["source_pdf"]), normalize_text(row["source_sha256"]))
        for row in rows
    }
    missing = sorted(expected_keys - set(entries))
    extra = sorted(set(entries) - expected_keys)
    if missing:
        report.add(
            "reference-cache-coverage",
            BLOCK,
            "Reference cache is missing entries required by the manifest.",
            {"missing_count": len(missing), "examples": _cap([m[0] for m in missing])},
        )
    if extra:
        report.add(
            "reference-cache-coverage",
            WARN,
            "Reference cache holds entries absent from the manifest.",
            {"extra_count": len(extra), "examples": _cap([e[0] for e in extra])},
        )


# ---------------------------------------------------------------------------
# Per-run reconciliation against catalog, consolidated report and manifest
# ---------------------------------------------------------------------------


def reconcile_run(
    run_dir: Path,
    catalog_entry: dict[str, Any] | None,
    summary_entry: dict[str, Any] | None,
    rows: list[dict[str, str]],
    entries: dict[tuple[str, str], dict[str, Any]],
    expected_cases: int,
    report: ReconciliationReport,
) -> dict[str, Any]:
    folder = run_dir.name
    observed: dict[str, Any] = {
        "folder": folder,
        "catalog_case_id": (catalog_entry or {}).get("case_id"),
        "outputs_found": 0,
        "succeeded": 0,
        "failed": 0,
        "join_mismatches": 0,
        "missing": [],
    }

    if catalog_entry is None:
        report.add(
            "unknown-local-run",
            WARN,
            "Local raw run is not referenced by the V1 run catalog.",
            {"folder": folder},
        )

    case_paths = sorted((run_dir / "cases").glob("case-*.json"))
    numbers = []
    parse_errors: list[str] = []
    join_problems: list[str] = []
    statuses: dict[str, int] = {}
    total_ms: list[int] = []

    for path in case_paths:
        match = re.fullmatch(r"case-(\d+)\.json", path.name)
        if match is None:
            parse_errors.append(f"{path.name}: unexpected filename")
            continue
        number = int(match.group(1))
        numbers.append(number)
        payload, error = read_json_or_none(path)
        if error:
            parse_errors.append(f"{path.name}: {error}")
            continue
        observed["outputs_found"] += 1
        status = str(payload.get("status", ""))
        statuses[status] = statuses.get(status, 0) + 1
        if status == "SUCCEEDED":
            observed["succeeded"] += 1
        elif status == "FAILED":
            observed["failed"] += 1
        if isinstance(payload.get("total_ms"), int):
            total_ms.append(int(payload["total_ms"]))

        row = rows[number - 1] if 1 <= number <= len(rows) else None
        if row is None:
            join_problems.append(f"case {number}: no manifest row")
            continue
        checks = (
            ("case_number", payload.get("case_number") == number),
            ("reference_pdf", payload.get("reference_pdf") == row.get("source_pdf")),
            (
                "reference_sha256",
                payload.get("reference_sha256") == row.get("source_sha256"),
            ),
            (
                "external_id",
                normalize_text(payload.get("external_id"))
                == Path(row.get("source_pdf", "")).stem,
            ),
            (
                "prompt_case_id",
                f"HOLDOUT-{number:04d}"
                in str((payload.get("input") or {}).get("prompt_text", "")),
            ),
        )
        for name, ok in checks:
            if not ok:
                join_problems.append(f"case {number}: {name} mismatch")
        key = (
            str(payload.get("reference_pdf")),
            str(payload.get("reference_sha256")),
        )
        if key not in entries and not any(join_problems):
            join_problems.append(f"case {number}: absent from reference cache")

    observed["missing"] = sorted(set(range(1, expected_cases + 1)) - set(numbers))
    observed["join_mismatches"] = len(join_problems)

    if parse_errors:
        report.add(
            "run-case-parse",
            BLOCK,
            f"Run {folder}: unreadable or misnamed case files.",
            {"errors": _cap(parse_errors)},
        )
    duplicates = {
        number for number in numbers if numbers.count(number) > 1
    }
    problems: list[str] = []
    if duplicates:
        problems.extend(f"duplicated case file {n}" for n in sorted(duplicates))
    if observed["missing"]:
        problems.append(
            f"{len(observed['missing'])} missing cases, e.g. "
            f"{observed['missing'][:MAX_DETAIL_EXAMPLES]}"
        )
    if problems:
        report.add(
            "run-completeness",
            BLOCK,
            f"Run {folder}: case set is not exactly 1..{expected_cases}.",
            {"problems": _cap(problems), "found": observed["outputs_found"]},
        )
    if join_problems:
        report.add(
            "run-joins",
            BLOCK,
            f"Run {folder}: strict case joins failed.",
            {
                "mismatch_count": len(join_problems),
                "examples": _cap(join_problems),
            },
        )

    progress, error = read_json_or_none(run_dir / "progress.json")
    if error:
        report.add(
            "run-progress-consistency",
            WARN,
            f"Run {folder}: progress.json unavailable ({error}).",
        )
    else:
        expected_progress = {
            "completed": observed["outputs_found"],
            "succeeded": observed["succeeded"],
            "failed": observed["failed"],
            "total": expected_cases,
        }
        drift = {
            key: {"recorded": progress.get(key), "observed": value}
            for key, value in expected_progress.items()
            if progress.get(key) != value
        }
        if drift:
            report.add(
                "run-progress-consistency",
                BLOCK,
                f"Run {folder}: progress.json disagrees with the case files.",
                {"drift": drift, "statuses": statuses},
            )

    summary_csv = run_dir / "summary.csv"
    if summary_csv.exists():
        csv_rows = read_csv_rows(summary_csv)
        csv_statuses: dict[str, int] = {}
        for row in csv_rows:
            csv_statuses[row.get("status", "")] = (
                csv_statuses.get(row.get("status", ""), 0) + 1
            )
        if len(csv_rows) != observed["outputs_found"] or csv_statuses != statuses:
            report.add(
                "run-summary-consistency",
                BLOCK,
                f"Run {folder}: summary.csv disagrees with the case files.",
                {
                    "csv_rows": len(csv_rows),
                    "case_files": observed["outputs_found"],
                    "csv_statuses": csv_statuses,
                    "case_statuses": statuses,
                },
            )
        recorded_median = (summary_entry or {}).get("latency_p50_ms")
        computed_median = observed_median_ms(total_ms)
        observed["latency_p50_observed_ms"] = computed_median
        if (
            summary_entry is not None
            and recorded_median is not None
            and computed_median is not None
            and abs(float(recorded_median) - float(computed_median))
            > LATENCY_TOLERANCE_MS
        ):
            report.add(
                "run-latency-p50-drift",
                WARN,
                f"Run {folder}: recomputed latency p50 differs from the consolidated value.",
                {
                    "recorded_ms": recorded_median,
                    "observed_ms": computed_median,
                    "tolerance_ms": LATENCY_TOLERANCE_MS,
                },
            )
    else:
        report.add(
            "run-summary-consistency",
            WARN,
            f"Run {folder}: summary.csv missing from the snapshot.",
        )

    if summary_entry is not None:
        drift = {
            column: {
                "recorded": summary_entry.get(column),
                "observed": observed[column],
            }
            for column in ("outputs_found", "succeeded", "failed")
            if summary_entry.get(column) != observed[column]
        }
        recorded_missing = summary_entry.get("missing")
        if recorded_missing != len(observed["missing"]):
            drift["missing"] = {
                "recorded": recorded_missing,
                "observed": len(observed["missing"]),
            }
        if drift:
            report.add(
                "run-consolidated-counts",
                BLOCK,
                f"Run {folder}: consolidated historical counts disagree with the raw outputs.",
                {"drift": drift},
            )
    return observed


def check_run_config_parity(
    run_dir: Path,
    catalog_entry: dict[str, Any],
    expected_cases: int,
    report: ReconciliationReport,
) -> None:
    experiment, error = read_json_or_none(run_dir / "experiment.yml")
    if error:
        report.add(
            "run-config-unreadable",
            WARN,
            f"Run {run_dir.name}: experiment.yml unreadable ({error}).",
        )
        return
    mismatches = []
    for experiment_key, catalog_key in EXPERIMENT_TO_CATALOG.items():
        left = experiment.get(experiment_key)
        right = catalog_entry.get(catalog_key)
        if not values_equal(left, right):
            mismatches.append(
                f"{catalog_key}: experiment={left!r} catalog={right!r}"
            )
    configuration, config_error = read_json_or_none(run_dir / "configuration.json")
    if config_error:
        report.add(
            "run-config-unreadable",
            WARN,
            f"Run {run_dir.name}: configuration.json unreadable ({config_error}).",
        )
    else:
        if configuration.get("requested_cases") not in (None, expected_cases):
            mismatches.append(
                f"requested_cases: configuration="
                f"{configuration.get('requested_cases')!r} expected={expected_cases!r}"
            )
        for key in ("top_k", "minimum_score"):
            left = configuration.get(key)
            right = catalog_entry.get(key)
            if left not in (None,) and not values_equal(left, right):
                mismatches.append(f"{key}: configuration={left!r} catalog={right!r}")
    if mismatches:
        report.add(
            "run-config-parity",
            BLOCK,
            f"Run {run_dir.name}: effective run parameters differ from the catalog entry.",
            {"mismatches": mismatches},
        )

# ---------------------------------------------------------------------------
# Consolidated report vs catalog, and CSV vs JSON consistency
# ---------------------------------------------------------------------------


def check_consolidated_vs_catalog(
    catalog_runs: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    report: ReconciliationReport,
) -> None:
    by_case_id = {entry.get("case_id"): entry for entry in catalog_runs}
    unknown = [
        entry.get("case_id") for entry in summaries if entry.get("case_id") not in by_case_id
    ]
    if unknown:
        report.add(
            "consolidated-unknown-runs",
            BLOCK,
            "Consolidated summary lists runs absent from the V1 catalog.",
            {"unknown_case_ids": unknown},
        )
    mismatches: list[str] = []
    for entry in summaries:
        catalog_entry = by_case_id.get(entry.get("case_id"))
        if catalog_entry is None:
            continue
        for key in CATALOG_PARAM_KEYS:
            if not values_equal(entry.get(key), catalog_entry.get(key)):
                mismatches.append(
                    f"{entry.get('case_id')} {key}: summary={entry.get(key)!r} "
                    f"catalog={catalog_entry.get(key)!r}"
                )
        recorded_path = str(catalog_entry.get("path", "")).replace("\\", "/")
        summary_path = str(entry.get("run_path", "")).replace("\\", "/")
        if (
            Path(recorded_path).name
            and Path(recorded_path).name != Path(summary_path).name
        ):
            mismatches.append(
                f"{entry.get('case_id')} run folder: summary={summary_path!r} "
                f"catalog={recorded_path!r}"
            )
    if mismatches:
        report.add(
            "consolidated-catalog-parity",
            BLOCK,
            "Consolidated run parameters disagree with the catalog.",
            {"mismatch_count": len(mismatches), "examples": _cap(mismatches)},
        )


def check_summary_csv_vs_json(
    summary: dict[str, Any], csv_rows: list[dict[str, str]], report: ReconciliationReport
) -> None:
    by_case_id = {
        entry.get("case_id"): entry for entry in summary.get("summaries", [])
    }
    problems: list[str] = []
    seen = set()
    for row in csv_rows:
        case_id = row.get("case_id")
        entry = by_case_id.get(case_id)
        if entry is None:
            problems.append(f"csv-only case_id {case_id}")
            continue
        seen.add(case_id)
        for column in SUMMARY_INT_COLUMNS:
            raw = row.get(column)
            if raw is None or raw == "":
                continue
            try:
                value = int(raw)
            except ValueError:
                problems.append(f"{case_id} {column}: non-integer {raw!r}")
                continue
            if not values_equal(value, entry.get(column)):
                problems.append(
                    f"{case_id} {column}: csv={value!r} json={entry.get(column)!r}"
                )
        for column in SUMMARY_FLOAT_COLUMNS:
            raw = row.get(column)
            if raw is None or raw == "":
                continue
            try:
                value = float(raw)
            except ValueError:
                problems.append(f"{case_id} {column}: non-float {raw!r}")
                continue
            if not values_equal(value, entry.get(column)):
                problems.append(
                    f"{case_id} {column}: csv={value!r} json={entry.get(column)!r}"
                )
        comparable_csv = row.get("comparable_full_run", "").strip().lower()
        if comparable_csv in {"true", "false"}:
            if (comparable_csv == "true") != bool(entry.get("comparable_full_run")):
                problems.append(
                    f"{case_id} comparable_full_run: csv={comparable_csv!r} "
                    f"json={entry.get('comparable_full_run')!r}"
                )
    json_only = sorted(set(by_case_id) - seen)
    if json_only:
        problems.append(f"json rows missing from csv: {json_only}")
    if problems:
        report.add(
            "summary-csv-json-drift",
            BLOCK,
            "benchmark-summary.csv disagrees with benchmark-summary.json.",
            {"problem_count": len(problems), "examples": _cap(problems)},
        )


# ---------------------------------------------------------------------------
# V1 performance report (004-benchmark-v1)
# ---------------------------------------------------------------------------


PERF_V1_DATASET_RELATIVE_PATH = Path("apps/api/tests/fixtures/benchmark_004_dataset.json")


def check_perf_v1_report(repo_root: Path, report: ReconciliationReport) -> None:
    report.add(
        "perf-v1-scope",
        INFO,
        "The 004-benchmark-v1 artifact measures API endpoint latency; it is "
        "informational and never comparable with generation-fidelity runs.",
    )
    path = repo_root / "apps/api/artifacts/benchmarks/004.json"
    payload, error = read_json_or_none(path)
    if error:
        report.add(
            "perf-v1-report",
            WARN,
            f"V1 performance report unavailable ({error}).",
            {"path": str(path)},
        )
        return
    if payload.get("schema_version") != PERF_V1_SCHEMA:
        report.add(
            "perf-v1-schema",
            BLOCK,
            "V1 performance report schema version drifted from 004-benchmark-v1.",
            {"actual": payload.get("schema_version")},
        )
    contract_drift = {}
    if payload.get("informational") is not True:
        contract_drift["informational"] = payload.get("informational")
    if payload.get("regression_alert") is not False:
        contract_drift["regression_alert"] = payload.get("regression_alert")
    if payload.get("alerts") != []:
        contract_drift["alerts"] = payload.get("alerts")
    if contract_drift:
        report.add(
            "perf-v1-contract",
            WARN,
            "V1 performance report no longer matches its informational contract.",
            contract_drift,
        )

    dataset = payload.get("dataset") or {}
    recorded_sha = dataset.get("sha256")
    fixture = repo_root / PERF_V1_DATASET_RELATIVE_PATH
    if fixture.exists():
        actual_sha = sha256_file(fixture)
        if recorded_sha and actual_sha != recorded_sha:
            report.add(
                "perf-v1-dataset-digest",
                WARN,
                "V1 performance report dataset digest does not match the current "
                "fixture file; regenerate or re-record before citing 004 results.",
                {
                    "fixture": dataset.get("path"),
                    "recorded": recorded_sha,
                    "actual": actual_sha,
                },
            )
    else:
        report.add(
            "perf-v1-dataset-digest",
            WARN,
            "V1 performance report dataset fixture is absent from this checkout.",
            {"fixture": dataset.get("path"), "recorded": recorded_sha},
        )

# ---------------------------------------------------------------------------
# Output safety and CLI
# ---------------------------------------------------------------------------


def resolve_output_path(raw: str, repo_root: Path, remote_dir: Path) -> Path:
    """Resolve and guard the report path.

    The report may only be written under ``<repo>/benchmark_v2`` or outside
    both input roots, so production artifacts and remote snapshots stay
    untouched.
    """
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.resolve()
    if candidate.is_relative_to(remote_dir):
        raise ValueError(
            f"refusing to write inside the remote snapshot: {candidate}"
        )
    benchmark_v2_root = (repo_root / "benchmark_v2").resolve()
    if candidate.is_relative_to(repo_root) and not candidate.is_relative_to(
        benchmark_v2_root
    ):
        raise ValueError(
            f"refusing to write outside benchmark_v2 within the repository: "
            f"{candidate}"
        )
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile V1 historical reports and run catalog with raw "
            "1000-case runs (read-only audit)."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root (default: two levels above this script).",
    )
    parser.add_argument(
        "--remote-dir",
        type=Path,
        required=True,
        help="Remote snapshot directory with manifest.csv, gold cache and run folders.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Report path (default: benchmark_v2/reports/v1-reconciliation.json).",
    )
    parser.add_argument(
        "--expected-prompt-manifest-sha256",
        default=FROZEN_PROMPT_MANIFEST_SHA256,
        help="Frozen digest documented for inputs-manifest.json.",
    )
    parser.add_argument(
        "--expected-reference-cache-sha256",
        default=FROZEN_REFERENCE_CACHE_SHA256,
        help="Frozen digest documented for pdf-gold-facts.auto.jsonl.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    remote_dir = args.remote_dir.resolve()
    output_arg = args.output or (
        repo_root / "benchmark_v2" / "reports" / "v1-reconciliation.json"
    )
    try:
        output_path = resolve_output_path(str(output_arg), repo_root, remote_dir)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    report = ReconciliationReport()
    holdout = repo_root / "docs/benchmarks/holdout-1000"
    inputs_manifest = holdout / "inputs-manifest.json"
    reference_cache = remote_dir / "pdf-gold-facts.auto.jsonl"
    catalog_path = holdout / "run-catalog.json"
    summary_json_path = holdout / "results/benchmark-summary.json"
    summary_csv_path = holdout / "results/benchmark-summary.csv"

    missing_inputs = [
        str(path)
        for path in (
            inputs_manifest,
            reference_cache,
            catalog_path,
            summary_json_path,
            summary_csv_path,
            remote_dir / "manifest.csv",
        )
        if not path.exists()
    ]
    if missing_inputs:
        report.add(
            "inputs-present",
            BLOCK,
            "Required reconciliation inputs are missing.",
            {"missing": missing_inputs},
        )

    check_perf_v1_report(repo_root, report)

    observed_runs: list[dict[str, Any]] = []
    if not missing_inputs:
        check_frozen_inputs(
            report,
            inputs_manifest,
            reference_cache,
            args.expected_prompt_manifest_sha256,
            args.expected_reference_cache_sha256,
        )

        manifest_payload = read_json(inputs_manifest)
        records = list(manifest_payload.get("records", []))
        rows = read_csv_rows(remote_dir / "manifest.csv")
        entries = load_reference_cache(reference_cache, report)

        catalog, error = read_json_or_none(catalog_path)
        if error:
            report.add("catalog-load", BLOCK, f"Run catalog unreadable ({error}).")
            catalog = {}
        summary, error = read_json_or_none(summary_json_path)
        if error:
            report.add(
                "consolidated-load", BLOCK, f"Consolidated summary unreadable ({error})."
            )
            summary = {}
        else:
            if summary.get("schema_version") != CONSOLIDATED_SCHEMA:
                report.add(
                    "consolidated-schema",
                    WARN,
                    "Consolidated summary schema version differs from decree-factual-fidelity.v2.",
                    {"actual": summary.get("schema_version")},
                )
            summaries = list(summary.get("summaries", []))
            check_summary_csv_vs_json(summary, read_csv_rows(summary_csv_path), report)
            check_consolidated_vs_catalog(check_catalog(catalog, report), summaries, report)

        check_manifest_equivalence(records, rows, report)
        check_reference_coverage(rows, entries, report)

        for run_dir in discover_run_dirs(remote_dir):
            folder = run_dir.name
            catalog_entry = None
            summary_entry = None
            catalog_runs = list(catalog.get("runs", []))
            entry = catalog_entry_for_folder(catalog_runs, folder)
            if entry is not None:
                catalog_entry = entry
                summary_entry = summary_entry_for_case(summary, str(entry.get("case_id")))
            expected_cases = int(catalog.get("expected_cases") or EXPECTED_CASES)
            observed = reconcile_run(
                run_dir,
                catalog_entry,
                summary_entry,
                rows,
                entries,
                expected_cases,
                report,
            )
            if catalog_entry is not None:
                check_run_config_parity(run_dir, catalog_entry, expected_cases, report)
            observed["catalog_case_id"] = (catalog_entry or {}).get("case_id")
            observed_runs.append(observed)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "repo_root": str(repo_root),
            "remote_dir": str(remote_dir),
            "expected_prompt_manifest_sha256": args.expected_prompt_manifest_sha256,
            "expected_reference_cache_sha256": args.expected_reference_cache_sha256,
        },
        "runs_reconciled": observed_runs,
        "findings": report.to_list(),
        "counts": report.counts(),
        "status": report.status(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for finding in report.findings:
        print(f"[{finding.severity}] {finding.check}: {finding.message}")
    counts = report.counts()
    print(
        f"reconciliation status={payload['status']} "
        f"(info={counts['info']}, warn={counts['warn']}, block={counts['block']})"
    )
    print(f"report: {output_path}")
    return 2 if report.blocks else 0


if __name__ == "__main__":
    raise SystemExit(main())
