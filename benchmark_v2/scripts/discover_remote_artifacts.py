"""Discover and reconcile remote benchmark v2 artifacts into a JSON/Markdown inventory.

The tool reads a snapshot directory of benchmark artifacts (holdout manifest,
PDF gold facts, prompt samples and one or more run directories) strictly in
read-only mode, reconciles every source against the others, and writes an
inventory in JSON and Markdown formats to an output directory outside the
snapshot.

Usage:
    python discover_remote_artifacts.py ROOT [--output-dir DIR]
        [--json-name NAME] [--markdown-name NAME] [--max-examples N]

Exit codes: 0 consistent, 1 inconsistencies found, 2 fatal input/output error.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "benchmark-v2/remote-artifact-inventory/v1"
CASE_FILE_PATTERN = re.compile(r"^case-(\d+)\.json$")
HOLDOUT_ID_PATTERN = re.compile(r"^HOLDOUT-(\d+)$")
PROMPT_PATTERN = re.compile(r"^prompt-\d+-\d+\.md$")
MANIFEST_NAME = "manifest.csv"
GOLD_FACTS_NAME = "pdf-gold-facts.auto.jsonl"
RUN_MARKER_FILES = (
    "configuration.json",
    "experiment.yml",
    "progress.json",
    "results.jsonl",
    "summary.csv",
    "runner.log",
)
DEFAULT_MAX_EXAMPLES = 20


@dataclass(frozen=True)
class FileDigest:
    name: str
    relative_path: str
    sha256: str | None
    bytes: int | None
    present: bool


@dataclass(frozen=True)
class ManifestRow:
    case_id: str
    case_number: int | None
    prompt_file: str
    source_pdf: str
    source_sha256: str
    quality_status: str


@dataclass(frozen=True)
class ManifestSummary:
    digest: FileDigest
    columns: tuple[str, ...]
    row_count: int
    parsed_rows: tuple[ManifestRow, ...]
    unparseable_case_ids: tuple[str, ...]
    duplicate_case_numbers: tuple[int, ...]
    quality_status_counts: dict[str, int]


@dataclass(frozen=True)
class GoldFactsSummary:
    digest: FileDigest
    record_count: int
    invalid_line_count: int
    blank_line_count: int
    pdfs: tuple[str, ...]
    sha256_by_pdf: dict[str, str]
    duplicate_pdfs: tuple[str, ...]


@dataclass(frozen=True)
class PromptsSummary:
    referenced_by_manifest: tuple[str, ...]
    present_on_disk: tuple[str, ...]


@dataclass(frozen=True)
class ResultRecord:
    case_number: int | None
    external_id: str | None
    status: str | None
    http_status: int | None
    rag_run_id: str | None
    reference_pdf: str | None
    reference_sha256: str | None
    retrieved: int | None
    selected: int | None


@dataclass(frozen=True)
class RunSources:
    configuration: dict[str, object]
    experiment: dict[str, object]
    progress: dict[str, object]
    digests: dict[str, FileDigest]
    case_numbers_from_files: tuple[int, ...]
    unparseable_case_files: tuple[str, ...]
    duplicate_case_files: tuple[int, ...]
    case_records: tuple[ResultRecord, ...]
    result_records: tuple[ResultRecord, ...]
    invalid_result_lines: int
    duplicate_result_numbers: tuple[int, ...]
    summary_rows: tuple[ResultRecord, ...]
    duplicate_summary_numbers: tuple[int, ...]
    failed_attempt_entries: int
    runner_log_lines: int
    runner_log_last_line: str


@dataclass(frozen=True)
class RunInventory:
    name: str
    relative_path: str
    detected: bool
    requested_cases: int | None
    start_case: int | None
    run_id: str | None
    sources: RunSources | None


@dataclass(frozen=True)
class Issue:
    code: str
    detail: str
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class CrossSourceMismatchExample:
    case_number: int
    field_name: str
    values: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Reconciliation:
    verdict: str
    issues: tuple[Issue, ...]
    notes: tuple[str, ...]
    manifest_vs_gold_facts: dict[str, object]
    runs: tuple[dict[str, object], ...]


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_optional(root: Path, relative: str) -> FileDigest:
    path = root / relative
    if not path.is_file():
        return FileDigest(
            name=path.name,
            relative_path=relative.replace("\\", "/"),
            sha256=None,
            bytes=None,
            present=False,
        )
    return FileDigest(
        name=path.name,
        relative_path=relative.replace("\\", "/"),
        sha256=_sha256_file(path),
        bytes=path.stat().st_size,
        present=True,
    )


def _opt_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _opt_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _parse_json_object(path: Path) -> dict[str, object]:
    text = _read_text(path)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}: expected a JSON object")
    return payload


def _parse_config_like(path: Path) -> dict[str, object]:
    """Parse JSON-first config files with a flat YAML fallback."""
    text = _read_text(path).strip()
    if text.startswith("{"):
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
        raise ValueError(f"{path.name}: expected an object")
    parsed: dict[str, object] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, raw_value = stripped.partition(":")
        value: object
        scalar = raw_value.strip().strip("'\"")
        if scalar == "":
            value = None
        elif scalar.lower() in {"null", "~"}:
            value = None
        elif scalar.lower() == "true":
            value = True
        elif scalar.lower() == "false":
            value = False
        else:
            try:
                value = int(scalar)
            except ValueError:
                try:
                    value = float(scalar)
                except ValueError:
                    value = scalar
        parsed[key.strip()] = value
    return parsed


def parse_manifest(path: Path) -> ManifestSummary:
    digest = _digest_optional(path.parent, path.name)
    text = _read_text(path)
    reader = csv.DictReader(io.StringIO(text))
    columns = tuple(reader.fieldnames or ())
    rows: list[ManifestRow] = []
    unparseable: list[str] = []
    seen_numbers: Counter[int] = Counter()
    quality_counter: Counter[str] = Counter()
    for row in reader:
        case_id = (row.get("case_id") or "").strip()
        match = HOLDOUT_ID_PATTERN.match(case_id)
        source_pdf = (row.get("source_pdf") or "").strip()
        source_sha256 = (row.get("source_sha256") or "").strip()
        quality_status = (row.get("quality_status") or "").strip()
        quality_counter[quality_status] += 1
        if match is None:
            unparseable.append(case_id)
            continue
        number = int(match.group(1))
        seen_numbers[number] += 1
        rows.append(
            ManifestRow(
                case_id=case_id,
                case_number=number,
                prompt_file=(row.get("prompt_file") or "").strip(),
                source_pdf=source_pdf,
                source_sha256=source_sha256,
                quality_status=quality_status,
            )
        )
    duplicates = tuple(sorted(n for n, c in seen_numbers.items() if c > 1))
    return ManifestSummary(
        digest=digest,
        columns=columns,
        row_count=sum(seen_numbers.values()) + len(unparseable),
        parsed_rows=tuple(sorted(rows, key=lambda item: item.case_number or 0)),
        unparseable_case_ids=tuple(unparseable),
        duplicate_case_numbers=duplicates,
        quality_status_counts=dict(sorted(quality_counter.items())),
    )


def parse_gold_facts(path: Path) -> GoldFactsSummary:
    digest = _digest_optional(path.parent, path.name)
    text = _read_text(path)
    record_count = 0
    invalid_lines = 0
    blank_lines = 0
    sha_by_pdf: dict[str, str] = {}
    duplicates: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            blank_lines += 1
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        if not isinstance(payload, dict):
            invalid_lines += 1
            continue
        record_count += 1
        pdf = payload.get("reference_pdf")
        sha = payload.get("reference_sha256")
        if isinstance(pdf, str):
            if pdf in sha_by_pdf:
                duplicates.append(pdf)
            if isinstance(sha, str):
                sha_by_pdf[pdf] = sha
    return GoldFactsSummary(
        digest=digest,
        record_count=record_count,
        invalid_line_count=invalid_lines,
        blank_line_count=blank_lines,
        pdfs=tuple(sorted(sha_by_pdf)),
        sha256_by_pdf=sha_by_pdf,
        duplicate_pdfs=tuple(sorted(set(duplicates))),
    )


def summarize_prompts(manifest: ManifestSummary, root: Path) -> PromptsSummary:
    referenced = tuple(
        dict.fromkeys(row.prompt_file for row in manifest.parsed_rows if row.prompt_file)
    )
    present = sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_file() and PROMPT_PATTERN.match(entry.name)
    )
    return PromptsSummary(
        referenced_by_manifest=referenced,
        present_on_disk=tuple(present),
    )


def _record_from_payload(payload: dict[str, object]) -> ResultRecord:
    return ResultRecord(
        case_number=_opt_int(payload, "case_number"),
        external_id=_opt_str(payload, "external_id"),
        status=_opt_str(payload, "status"),
        http_status=_opt_int(payload, "http_status"),
        rag_run_id=_opt_str(payload, "rag_run_id"),
        reference_pdf=_opt_str(payload, "reference_pdf"),
        reference_sha256=_opt_str(payload, "reference_sha256"),
        retrieved=_opt_int(payload, "retrieved"),
        selected=_opt_int(payload, "selected"),
    )


def _summary_record(row: dict[str, str]) -> ResultRecord:
    def to_int(raw: str | None) -> int | None:
        if raw is None or raw.strip() == "":
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    return ResultRecord(
        case_number=to_int(row.get("case_number")),
        external_id=(row.get("external_id") or "").strip() or None,
        status=(row.get("status") or "").strip() or None,
        http_status=to_int(row.get("http_status")),
        rag_run_id=(row.get("rag_run_id") or "").strip() or None,
        reference_pdf=None,
        reference_sha256=None,
        retrieved=to_int(row.get("retrieved")),
        selected=to_int(row.get("selected")),
    )


def analyze_run(run_dir: Path) -> RunSources:
    configuration: dict[str, object] = {}
    config_path = run_dir / "configuration.json"
    if config_path.is_file():
        configuration = _parse_json_object(config_path)

    experiment: dict[str, object] = {}
    experiment_path = run_dir / "experiment.yml"
    if experiment_path.is_file():
        try:
            experiment = _parse_config_like(experiment_path)
        except ValueError:
            experiment = {}

    progress: dict[str, object] = {}
    progress_path = run_dir / "progress.json"
    if progress_path.is_file():
        try:
            progress = _parse_json_object(progress_path)
        except ValueError:
            progress = {}

    digests = {
        name: _digest_optional(run_dir, name) for name in (*RUN_MARKER_FILES, "compose.benchmark.yaml")
    }

    case_numbers: list[int] = []
    case_records: list[ResultRecord] = []
    unparseable_files: list[str] = []
    cases_dir = run_dir / "cases"
    seen_case_numbers: Counter[int] = Counter()
    if cases_dir.is_dir():
        for entry in sorted(cases_dir.iterdir()):
            match = CASE_FILE_PATTERN.match(entry.name)
            if entry.is_file() and match:
                number = int(match.group(1))
                seen_case_numbers[number] += 1
                try:
                    payload = _parse_json_object(entry)
                except (ValueError, json.JSONDecodeError):
                    unparseable_files.append(f"cases/{entry.name}")
                    continue
                case_numbers.append(_opt_int(payload, "case_number") or number)
                case_records.append(_record_from_payload(payload))

    result_records: list[ResultRecord] = []
    invalid_result_lines = 0
    seen_result_numbers: Counter[int] = Counter()
    results_path = run_dir / "results.jsonl"
    if results_path.is_file():
        for line in _read_text(results_path).splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                invalid_result_lines += 1
                continue
            if not isinstance(payload, dict):
                invalid_result_lines += 1
                continue
            record = _record_from_payload(payload)
            if record.case_number is not None:
                seen_result_numbers[record.case_number] += 1
            result_records.append(record)

    summary_rows: list[ResultRecord] = []
    seen_summary_numbers: Counter[int] = Counter()
    summary_path = run_dir / "summary.csv"
    if summary_path.is_file():
        reader = csv.DictReader(io.StringIO(_read_text(summary_path)))
        for row in reader:
            record = _summary_record(row)
            if record.case_number is not None:
                seen_summary_numbers[record.case_number] += 1
            summary_rows.append(record)

    failed_attempts = run_dir / "failed-attempts"
    failed_entries = (
        sum(1 for _ in failed_attempts.rglob("*")) if failed_attempts.is_dir() else 0
    )

    runner_lines = 0
    runner_last = ""
    runner_path = run_dir / "runner.log"
    if runner_path.is_file():
        lines = _read_text(runner_path).splitlines()
        runner_lines = len(lines)
        runner_last = lines[-1].strip() if lines else ""

    return RunSources(
        configuration=configuration,
        experiment=experiment,
        progress=progress,
        digests=digests,
        case_numbers_from_files=tuple(sorted(case_numbers)),
        unparseable_case_files=tuple(unparseable_files),
        duplicate_case_files=tuple(
            sorted(n for n, c in seen_case_numbers.items() if c > 1)
        ),
        case_records=tuple(case_records),
        result_records=tuple(result_records),
        invalid_result_lines=invalid_result_lines,
        duplicate_result_numbers=tuple(
            sorted(n for n, c in seen_result_numbers.items() if c > 1)
        ),
        summary_rows=tuple(summary_rows),
        duplicate_summary_numbers=tuple(
            sorted(n for n, c in seen_summary_numbers.items() if c > 1)
        ),
        failed_attempt_entries=failed_entries,
        runner_log_lines=runner_lines,
        runner_log_last_line=runner_last,
    )


def detect_runs(root: Path) -> list[Path]:
    runs: list[Path] = []
    if not root.is_dir():
        return runs
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if any((entry / marker).is_file() for marker in RUN_MARKER_FILES):
            runs.append(entry)
    return runs


def _index_by_case(records: tuple[ResultRecord, ...]) -> dict[int, ResultRecord]:
    indexed: dict[int, ResultRecord] = {}
    for record in records:
        if record.case_number is not None:
            indexed.setdefault(record.case_number, record)
    return indexed


def _compare_sources(
    run_name: str,
    sources: RunSources,
    max_examples: int,
    issues: list[Issue],
) -> dict[str, object]:
    files_by_number = _index_by_case(sources.case_records)
    results_by_number = _index_by_case(sources.result_records)
    summary_by_number = _index_by_case(sources.summary_rows)
    shared = sorted(
        set(files_by_number) & set(results_by_number) & set(summary_by_number)
    )
    comparable_fields = (
        "external_id",
        "status",
        "http_status",
        "rag_run_id",
        "retrieved",
        "selected",
    )
    mismatches: list[CrossSourceMismatchExample] = []
    mismatch_total = 0
    for number in shared:
        triples = {
            "case_file": files_by_number[number],
            "results_jsonl": results_by_number[number],
            "summary_csv": summary_by_number[number],
        }
        for field_name in comparable_fields:
            values: dict[str, object] = {}
            for source_name, record in triples.items():
                value = getattr(record, field_name)
                if value is not None:
                    values[source_name] = value
            distinct = {repr(v) for v in values.values()}
            if len(distinct) > 1:
                mismatch_total += 1
                if len(mismatches) < max_examples:
                    mismatches.append(
                        CrossSourceMismatchExample(
                            case_number=number,
                            field_name=field_name,
                            values=tuple(
                                (source, repr(values[source]))
                                for source in sorted(values)
                            ),
                        )
                    )
    if mismatch_total:
        issues.append(
            Issue(
                code="CROSS_SOURCE_MISMATCH",
                detail=(
                    f"run '{run_name}': {mismatch_total} field disagreements across "
                    "case files, results.jsonl and summary.csv"
                ),
                examples=tuple(
                    f"case {example.case_number} {example.field_name}: "
                    + ", ".join(f"{source}={value}" for source, value in example.values)
                    for example in mismatches
                ),
            )
        )

    missing_in_results = sorted(
        set(files_by_number) - set(results_by_number)
    )[:max_examples]
    if missing_in_results:
        issues.append(
            Issue(
                code="RESULTS_MISSING_CASES",
                detail=(
                    f"run '{run_name}': {len(missing_in_results)}+ case files without "
                    "a results.jsonl entry"
                ),
                examples=tuple(str(n) for n in missing_in_results),
            )
        )
    missing_in_summary = sorted(
        set(files_by_number) - set(summary_by_number)
    )[:max_examples]
    if missing_in_summary:
        issues.append(
            Issue(
                code="SUMMARY_MISSING_CASES",
                detail=(
                    f"run '{run_name}': {len(missing_in_summary)}+ case files without "
                    "a summary.csv row"
                ),
                examples=tuple(str(n) for n in missing_in_summary),
            )
        )

    return {
        "shared_case_numbers": len(shared),
        "cross_source_fields_compared": list(comparable_fields),
        "cross_source_mismatches": mismatch_total,
        "mismatch_examples": [
            {
                "case_number": example.case_number,
                "field": example.field_name,
                "values": {source: value for source, value in example.values},
            }
            for example in mismatches
        ],
    }


def reconcile_run(
    run: RunInventory,
    manifest: ManifestSummary | None,
    max_examples: int,
    issues: list[Issue],
    notes: list[str],
) -> dict[str, object]:
    detail: dict[str, object] = {
        "name": run.name,
        "relative_path": run.relative_path,
        "detected": run.detected,
    }
    if run.sources is None:
        issues.append(
            Issue(
                code="RUN_INCOMPLETE",
                detail=f"run '{run.name}' lacks its marker files",
            )
        )
        detail["sources"] = None
        return detail

    sources = run.sources
    status_counter = Counter(record.status or "<missing>" for record in sources.result_records)
    detail["configuration"] = {
        "run_id": run.run_id,
        "requested_cases": run.requested_cases,
        "start_case": run.start_case,
        "top_k": _opt_int(sources.configuration, "top_k"),
        "minimum_score": sources.configuration.get("minimum_score"),
        "api_base_url": _opt_str(sources.configuration, "api_base_url"),
        "started_at": _opt_str(sources.configuration, "started_at"),
        "execution": _opt_str(sources.configuration, "execution"),
    }
    detail["experiment"] = {
        "id": _opt_str(sources.experiment, "id"),
        "embedding_model": _opt_str(sources.experiment, "embedding_model"),
        "dimensions": _opt_int(sources.experiment, "dimensions"),
        "ollama_context_length": _opt_int(sources.experiment, "ollama_context_length"),
        "rag_context_tokens": _opt_int(sources.experiment, "rag_context_tokens"),
        "rag_context_bytes": _opt_int(sources.experiment, "rag_context_bytes"),
        "output_tokens": _opt_int(sources.experiment, "output_tokens"),
        "minimum_score": sources.experiment.get("minimum_score"),
    }
    detail["progress"] = {
        "completed": _opt_int(sources.progress, "completed"),
        "succeeded": _opt_int(sources.progress, "succeeded"),
        "failed": _opt_int(sources.progress, "failed"),
        "total": _opt_int(sources.progress, "total"),
    }
    detail["counts"] = {
        "case_files": len(sources.case_numbers_from_files),
        "unparseable_case_files": len(sources.unparseable_case_files),
        "result_records": len(sources.result_records),
        "invalid_result_lines": sources.invalid_result_lines,
        "summary_rows": len(sources.summary_rows),
        "failed_attempt_entries": sources.failed_attempt_entries,
        "runner_log_lines": sources.runner_log_lines,
    }
    detail["status_distribution"] = dict(sorted(status_counter.items()))
    detail["runner_log_last_line"] = sources.runner_log_last_line
    detail["file_digests"] = {
        name: {
            "present": digest.present,
            "bytes": digest.bytes,
            "sha256": digest.sha256,
        }
        for name, digest in sorted(sources.digests.items())
    }

    for dup in sources.duplicate_case_files[:max_examples]:
        issues.append(
            Issue(
                code="DUPLICATE_CASE_FILES",
                detail=f"run '{run.name}': duplicated case number in cases/",
                examples=(str(dup),),
            )
        )
    if sources.unparseable_case_files:
        issues.append(
            Issue(
                code="CASE_FILES_UNPARSEABLE",
                detail=(
                    f"run '{run.name}': {len(sources.unparseable_case_files)} case "
                    "files are not valid JSON objects"
                ),
                examples=sources.unparseable_case_files[:max_examples],
            )
        )
    if sources.invalid_result_lines:
        issues.append(
            Issue(
                code="RESULTS_LINES_INVALID",
                detail=(
                    f"run '{run.name}': {sources.invalid_result_lines} invalid "
                    "results.jsonl lines"
                ),
            )
        )
    if sources.duplicate_result_numbers:
        issues.append(
            Issue(
                code="DUPLICATE_RESULT_NUMBERS",
                detail=(
                    f"run '{run.name}': duplicated case_number values in "
                    "results.jsonl"
                ),
                examples=tuple(
                    str(n) for n in sources.duplicate_result_numbers[:max_examples]
                ),
            )
        )
    if sources.duplicate_summary_numbers:
        issues.append(
            Issue(
                code="DUPLICATE_SUMMARY_NUMBERS",
                detail=(
                    f"run '{run.name}': duplicated case_number values in summary.csv"
                ),
                examples=tuple(
                    str(n) for n in sources.duplicate_summary_numbers[:max_examples]
                ),
            )
        )

    expected_range: set[int] = set()
    if run.requested_cases is not None and run.start_case is not None:
        expected_range = set(
            range(run.start_case, run.start_case + run.requested_cases)
        )
    elif manifest is not None and manifest.parsed_rows:
        expected_range = {
            row.case_number for row in manifest.parsed_rows if row.case_number is not None
        }
    if expected_range:
        present = set(sources.case_numbers_from_files)
        missing = sorted(expected_range - present)[:max_examples]
        extra = sorted(present - expected_range)[:max_examples]
        if missing:
            issues.append(
                Issue(
                    code="CASE_FILES_MISSING",
                    detail=(
                        f"run '{run.name}': {len(missing)}+ expected case files "
                        "absent from cases/"
                    ),
                    examples=tuple(str(n) for n in missing),
                )
            )
        if extra:
            issues.append(
                Issue(
                    code="CASE_FILES_UNEXPECTED",
                    detail=(
                        f"run '{run.name}': {len(extra)}+ case files outside the "
                        "expected range"
                    ),
                    examples=tuple(str(n) for n in extra),
                )
            )

    completed = _opt_int(sources.progress, "completed")
    succeeded = _opt_int(sources.progress, "succeeded")
    failed = _opt_int(sources.progress, "failed")
    if completed is not None and completed != len(sources.result_records):
        issues.append(
            Issue(
                code="PROGRESS_COUNT_MISMATCH",
                detail=(
                    f"run '{run.name}': progress.completed={completed} but "
                    f"{len(sources.result_records)} results.jsonl records"
                ),
            )
        )
    if succeeded is not None and failed is not None and completed is not None:
        if succeeded + failed != completed:
            issues.append(
                Issue(
                    code="PROGRESS_SUM_MISMATCH",
                    detail=(
                        f"run '{run.name}': succeeded({succeeded}) + failed({failed}) "
                        f"!= completed({completed})"
                    ),
                )
            )

    cross = _compare_sources(run.name, sources, max_examples, issues)

    manifest_link: dict[str, object] = {"checked": False}
    if manifest is not None and manifest.parsed_rows:
        manifest_by_number = {
            row.case_number: row for row in manifest.parsed_rows if row.case_number is not None
        }
        results_by_number = _index_by_case(sources.result_records)
        shared = sorted(set(manifest_by_number) & set(results_by_number))
        pdf_mismatch = 0
        sha_mismatch = 0
        examples: list[str] = []
        for number in shared:
            manifest_row = manifest_by_number[number]
            record = results_by_number[number]
            if (
                record.reference_pdf is not None
                and record.reference_pdf != manifest_row.source_pdf
            ):
                pdf_mismatch += 1
                if len(examples) < max_examples:
                    examples.append(
                        f"case {number}: pdf manifest={manifest_row.source_pdf} "
                        f"results={record.reference_pdf}"
                    )
            if (
                record.reference_sha256 is not None
                and record.reference_sha256 != manifest_row.source_sha256
            ):
                sha_mismatch += 1
                if len(examples) < max_examples * 2:
                    examples.append(
                        f"case {number}: sha manifest={manifest_row.source_sha256[:12]}… "
                        f"results={record.reference_sha256[:12]}…"
                    )
        if pdf_mismatch or sha_mismatch:
            issues.append(
                Issue(
                    code="MANIFEST_REFERENCE_MISMATCH",
                    detail=(
                        f"run '{run.name}': {pdf_mismatch} pdf name and {sha_mismatch} "
                        "sha256 disagreements between manifest.csv and results.jsonl"
                    ),
                    examples=tuple(examples),
                )
            )
        manifest_link = {
            "checked": True,
            "shared_case_numbers": len(shared),
            "pdf_name_mismatches": pdf_mismatch,
            "sha256_mismatches": sha_mismatch,
        }
    else:
        notes.append(
            f"run '{run.name}': manifest.csv unavailable; reference linkage skipped"
        )
    detail["manifest_linkage"] = manifest_link
    detail["cross_source"] = cross
    return detail


def reconcile_manifest_vs_gold_facts(
    manifest: ManifestSummary | None,
    gold: GoldFactsSummary | None,
    issues: list[Issue],
    notes: list[str],
) -> dict[str, object]:
    summary: dict[str, object] = {
        "manifest_present": manifest is not None,
        "gold_facts_present": gold is not None,
    }
    if manifest is None:
        notes.append("manifest.csv missing; holdout coverage cannot be verified")
        return summary
    if gold is None:
        issues.append(
            Issue(code="GOLD_FACTS_MISSING", detail="pdf-gold-facts.auto.jsonl missing")
        )
        return summary

    manifest_pdfs = {row.source_pdf: row.source_sha256 for row in manifest.parsed_rows}
    gold_pdfs = set(gold.pdfs)
    missing = sorted(set(manifest_pdfs) - gold_pdfs)
    unexpected = sorted(gold_pdfs - set(manifest_pdfs))
    hash_mismatches = sorted(
        pdf
        for pdf, sha in manifest_pdfs.items()
        if pdf in gold.sha256_by_pdf and gold.sha256_by_pdf[pdf] != sha
    )
    summary.update(
        {
            "manifest_pdfs": len(manifest_pdfs),
            "gold_fact_records": gold.record_count,
            "covered_pdfs": len(set(manifest_pdfs) & gold_pdfs),
            "missing_in_gold_facts": missing,
            "unexpected_in_gold_facts": unexpected,
            "sha256_mismatches": hash_mismatches,
        }
    )
    if missing:
        issues.append(
            Issue(
                code="GOLD_FACTS_COVERAGE_GAP",
                detail=(
                    f"{len(missing)} manifest PDFs have no gold-facts record "
                    "(first ones listed as examples)"
                ),
                examples=tuple(missing[:DEFAULT_MAX_EXAMPLES]),
            )
        )
    if unexpected:
        issues.append(
            Issue(
                code="GOLD_FACTS_UNEXPECTED_ENTRIES",
                detail=(
                    f"{len(unexpected)} gold-facts PDFs are not present in manifest.csv"
                ),
                examples=tuple(unexpected[:DEFAULT_MAX_EXAMPLES]),
            )
        )
    if hash_mismatches:
        issues.append(
            Issue(
                code="GOLD_FACTS_SHA256_MISMATCH",
                detail=(
                    f"{len(hash_mismatches)} gold-facts records disagree with "
                    "manifest.csv source_sha256"
                ),
                examples=tuple(hash_mismatches[:DEFAULT_MAX_EXAMPLES]),
            )
        )
    if gold.invalid_line_count:
        issues.append(
            Issue(
                code="GOLD_FACTS_LINES_INVALID",
                detail=f"{gold.invalid_line_count} invalid lines in gold facts JSONL",
            )
        )
    if gold.duplicate_pdfs:
        issues.append(
            Issue(
                code="GOLD_FACTS_DUPLICATE_PDFS",
                detail=f"{len(gold.duplicate_pdfs)} duplicated PDF entries",
                examples=tuple(gold.duplicate_pdfs[:DEFAULT_MAX_EXAMPLES]),
            )
        )
    return summary


def build_inventory(
    root: Path,
    output_dir: Path,
    max_examples: int,
    generated_at: str | None = None,
) -> tuple[dict[str, object], str]:
    if not root.is_dir():
        raise FileNotFoundError(f"root directory does not exist: {root}")

    manifest_path = root / MANIFEST_NAME
    manifest = parse_manifest(manifest_path) if manifest_path.is_file() else None
    gold_path = root / GOLD_FACTS_NAME
    gold = parse_gold_facts(gold_path) if gold_path.is_file() else None
    prompts = summarize_prompts(manifest, root) if manifest else PromptsSummary((), ())

    issues: list[Issue] = []
    notes: list[str] = []

    if manifest is None:
        issues.append(Issue(code="MANIFEST_MISSING", detail="manifest.csv not found"))
    else:
        if manifest.unparseable_case_ids:
            issues.append(
                Issue(
                    code="MANIFEST_IDS_UNPARSEABLE",
                    detail=(
                        f"{len(manifest.unparseable_case_ids)} case_id values do not "
                        "match HOLDOUT-NNNN"
                    ),
                    examples=manifest.unparseable_case_ids[:DEFAULT_MAX_EXAMPLES],
                )
            )
        if manifest.duplicate_case_numbers:
            issues.append(
                Issue(
                    code="MANIFEST_DUPLICATE_CASE_NUMBERS",
                    detail=(
                        f"{len(manifest.duplicate_case_numbers)} duplicated case "
                        "numbers in manifest.csv"
                    ),
                    examples=tuple(
                        str(n) for n in manifest.duplicate_case_numbers[:DEFAULT_MAX_EXAMPLES]
                    ),
                )
            )

    manifest_vs_gold = reconcile_manifest_vs_gold_facts(manifest, gold, issues, notes)

    run_details: list[dict[str, object]] = []
    for run_path in detect_runs(root):
        configuration: dict[str, object] = {}
        config_path = run_path / "configuration.json"
        if config_path.is_file():
            try:
                configuration = _parse_json_object(config_path)
            except ValueError:
                configuration = {}
        sources = analyze_run(run_path)
        run = RunInventory(
            name=run_path.name,
            relative_path=run_path.relative_to(root).as_posix(),
            detected=True,
            requested_cases=_opt_int(configuration, "requested_cases"),
            start_case=_opt_int(configuration, "start_case"),
            run_id=_opt_str(configuration, "run_id"),
            sources=sources,
        )
        run_details.append(reconcile_run(run, manifest, max_examples, issues, notes))

    if not run_details:
        notes.append("no benchmark run directories detected under the snapshot root")

    verdict = "CONSISTENT" if not issues else "INCONSISTENT"

    inventory: dict[str, object] = {
        "schema": SCHEMA_VERSION,
        "generated_at_utc": generated_at
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": {
            "path": str(root),
            "exists": root.exists(),
        },
        "output_dir": str(output_dir),
        "top_level_files": {
            "manifest": {
                "present": manifest is not None,
                "rows": manifest.row_count if manifest else 0,
                "columns": list(manifest.columns) if manifest else [],
                "quality_status_counts": manifest.quality_status_counts
                if manifest
                else {},
                "sha256": manifest.digest.sha256 if manifest else None,
                "bytes": manifest.digest.bytes if manifest else None,
            },
            "gold_facts": {
                "present": gold is not None,
                "records": gold.record_count if gold else 0,
                "invalid_lines": gold.invalid_line_count if gold else 0,
                "sha256": gold.digest.sha256 if gold else None,
                "bytes": gold.digest.bytes if gold else None,
            },
            "prompts": {
                "referenced_by_manifest": len(prompts.referenced_by_manifest),
                "present_on_disk": len(prompts.present_on_disk),
                "present_names": prompts.present_on_disk[:DEFAULT_MAX_EXAMPLES],
            },
        },
        "runs": run_details,
        "reconciliation": {
            "verdict": verdict,
            "issue_count": len(issues),
            "issues": [
                {"code": issue.code, "detail": issue.detail, "examples": list(issue.examples)}
                for issue in issues
            ],
            "notes": notes,
            "manifest_vs_gold_facts": manifest_vs_gold,
        },
    }
    markdown = render_markdown(inventory)
    return inventory, markdown


def render_markdown(inventory: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("# Inventario de artefactos remotos — benchmark v2")
    lines.append("")
    lines.append(f"- Esquema: `{inventory['schema']}`")
    lines.append(f"- Generado: `{inventory['generated_at_utc']}`")
    root = inventory["root"]
    assert isinstance(root, dict)
    lines.append(f"- Raíz inspeccionada: `{root['path']}`")
    lines.append("")

    top_level = inventory["top_level_files"]
    assert isinstance(top_level, dict)
    manifest = top_level["manifest"]
    assert isinstance(manifest, dict)
    gold = top_level["gold_facts"]
    assert isinstance(gold, dict)
    prompts = top_level["prompts"]
    assert isinstance(prompts, dict)

    lines.append("## Archivos de nivel superior")
    lines.append("")
    lines.append("| Archivo | Presente | Registros/filas | Bytes | SHA-256 |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(
        f"| manifest.csv | {'sí' if manifest['present'] else 'no'} "
        f"| {manifest['rows']} | {manifest['bytes']} | {_short_sha(manifest['sha256'])} |"
    )
    lines.append(
        f"| pdf-gold-facts.auto.jsonl | {'sí' if gold['present'] else 'no'} "
        f"| {gold['records']} | {gold['bytes']} | {_short_sha(gold['sha256'])} |"
    )
    lines.append("")
    lines.append(
        f"- Prompts referenciados por el manifiesto: **{prompts['referenced_by_manifest']}**"
    )
    lines.append(f"- Prompts presentes en el snapshot: **{prompts['present_on_disk']}**")
    present_names = prompts.get("present_names")
    if isinstance(present_names, list) and present_names:
        lines.append(f"- Ejemplos: {', '.join(f'`{name}`' for name in present_names)}")
    lines.append("")

    runs = inventory["runs"]
    assert isinstance(runs, list)
    lines.append("## Corridas detectadas")
    lines.append("")
    if not runs:
        lines.append("_Ninguna corrida detectada._")
    for run in runs:
        assert isinstance(run, dict)
        lines.append(f"### `{run['name']}`")
        lines.append("")
        configuration = run.get("configuration")
        if isinstance(configuration, dict):
            lines.append(f"- run_id: `{configuration.get('run_id')}`")
            lines.append(
                f"- casos solicitados/inicio: "
                f"`{configuration.get('requested_cases')}`/`{configuration.get('start_case')}`"
            )
        counts = run.get("counts")
        if isinstance(counts, dict):
            lines.append(f"- archivos de caso: **{counts.get('case_files')}**")
            lines.append(f"- registros en results.jsonl: **{counts.get('result_records')}**")
            lines.append(f"- filas en summary.csv: **{counts.get('summary_rows')}**")
            lines.append(
                f"- entradas en failed-attempts: **{counts.get('failed_attempt_entries')}**"
            )
        status_distribution = run.get("status_distribution")
        if isinstance(status_distribution, dict) and status_distribution:
            rendered = ", ".join(
                f"`{key}`: {value}" for key, value in status_distribution.items()
            )
            lines.append(f"- estados: {rendered}")
        cross = run.get("cross_source")
        if isinstance(cross, dict):
            lines.append(
                f"- desacuerdos entre fuentes (caso/results/summary): "
                f"**{cross.get('cross_source_mismatches')}**"
            )
        linkage = run.get("manifest_linkage")
        if isinstance(linkage, dict) and linkage.get("checked"):
            lines.append(
                f"- enlace con manifest.csv: {linkage.get('shared_case_numbers')} casos "
                f"compartidos, {linkage.get('pdf_name_mismatches')} diferencias de PDF, "
                f"{linkage.get('sha256_mismatches')} diferencias de SHA-256"
            )
        lines.append("")

    reconciliation = inventory["reconciliation"]
    assert isinstance(reconciliation, dict)
    lines.append("## Conciliación")
    lines.append("")
    lines.append(f"- Veredicto: **{reconciliation['verdict']}**")
    lines.append(f"- Hallazgos: **{reconciliation['issue_count']}**")
    manifest_vs_gold = reconciliation.get("manifest_vs_gold_facts")
    if isinstance(manifest_vs_gold, dict):
        lines.append(
            f"- Cobertura gold-facts: {manifest_vs_gold.get('covered_pdfs')}/"
            f"{manifest_vs_gold.get('manifest_pdfs')} PDFs del manifiesto"
        )
    notes = reconciliation.get("notes")
    if isinstance(notes, list) and notes:
        lines.append("")
        lines.append("### Notas")
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")
    issues = reconciliation.get("issues")
    lines.append("")
    if isinstance(issues, list) and issues:
        lines.append("### Hallazgos")
        lines.append("")
        lines.append("| Código | Detalle | Ejemplos |")
        lines.append("| --- | --- | --- |")
        for issue in issues:
            assert isinstance(issue, dict)
            examples = issue.get("examples")
            example_text = (
                "; ".join(str(item) for item in examples) if examples else "—"
            )
            lines.append(
                f"| `{issue['code']}` | {issue['detail']} | {example_text} |"
            )
    else:
        lines.append("Sin hallazgos: todas las fuentes concuerdan.")
    lines.append("")
    return "\n".join(lines)


def _short_sha(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "—"
    return value[:16] + "…"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover and reconcile remote benchmark v2 artifacts."
    )
    parser.add_argument("root", type=Path, help="Snapshot directory (read-only)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for the JSON/Markdown inventory (outside ROOT)",
    )
    parser.add_argument("--json-name", default="artifact_inventory.json")
    parser.add_argument("--markdown-name", default="artifact_inventory.md")
    parser.add_argument("--max-examples", type=int, default=DEFAULT_MAX_EXAMPLES)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    default_output = Path(__file__).resolve().parent.parent / "inventory"
    output_dir = (args.output_dir or default_output).resolve()

    try:
        output_dir.relative_to(root)
    except ValueError:
        pass
    else:
        print(
            "ERROR: output-dir must be outside the read-only snapshot root",
            file=sys.stderr,
        )
        return 2

    try:
        inventory, markdown = build_inventory(
            root=root,
            output_dir=output_dir,
            max_examples=max(args.max_examples, 0),
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / args.json_name
    md_path = output_dir / args.markdown_name
    json_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")

    reconciliation = inventory["reconciliation"]
    assert isinstance(reconciliation, dict)
    print(f"JSON inventory: {json_path}")
    print(f"Markdown inventory: {md_path}")
    print(f"Verdict: {reconciliation['verdict']} ({reconciliation['issue_count']} findings)")
    return 0 if reconciliation["verdict"] == "CONSISTENT" else 1


if __name__ == "__main__":
    sys.exit(main())
