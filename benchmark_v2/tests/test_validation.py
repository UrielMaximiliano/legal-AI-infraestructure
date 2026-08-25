"""Adversarial validation of the versioned benchmark-v2 evidence surface.

These tests read only artifacts already committed to the repository.  They do
not create PDFs, prompts, reference caches, model outputs, or other benchmark
evidence.  Any mutation used below is an in-memory copy of a real row and is
used only to prove that the corresponding guard would reject a bad join.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from benchmark_v2.data.hashing import sha256_file
from benchmark_v2.results.schema import ContractError, build_metadata, build_result


REPO_ROOT = Path(__file__).resolve().parents[2]
HOLDOUT_ROOT = REPO_ROOT / "docs" / "benchmarks" / "holdout-1000"
MANIFEST_PATH = HOLDOUT_ROOT / "inputs-manifest.json"
CATALOG_PATH = HOLDOUT_ROOT / "run-catalog.json"
SUMMARY_PATH = HOLDOUT_ROOT / "results" / "benchmark-summary.json"
CASE_METRICS_PATH = HOLDOUT_ROOT / "results" / "benchmark-case-metrics.csv"
SCHEMA_PATH = REPO_ROOT / "benchmark_v2" / "configs" / "schema.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_CASES = 1000
EXPECTED_RUNS = 19
EXPECTED_MANIFEST_SHA256 = "26b72644e00ee44aff6fcb492aed616d6d4a438b44ed6d5abed3c5541697a930"


@pytest.fixture(scope="session")
def artifacts() -> dict[str, Any]:
    """Load the committed audit artifacts once for all validation checks."""

    return {
        "manifest": json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
        "catalog": json.loads(CATALOG_PATH.read_text(encoding="utf-8")),
        "summary": json.loads(SUMMARY_PATH.read_text(encoding="utf-8")),
        "rows": _read_case_rows(),
    }


def _manifest_by_number(manifest: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(str(record["case_id"]).split("-")[-1]): dict(record)
        for record in manifest["records"]
    }


def _read_case_rows() -> list[dict[str, str]]:
    with CASE_METRICS_PATH.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _rows_by_run(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["case_id"]].append(row)
    return dict(grouped)


def _prompt_hashes_by_number(rows: list[dict[str, str]]) -> dict[int, set[str]]:
    hashes: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        hashes[int(row["case_number"])].add(row["prompt_sha256"])
    return dict(hashes)


def _join_errors(
    rows: list[dict[str, str]],
    manifest_by_number: Mapping[int, Mapping[str, Any]],
    prompt_hashes: Mapping[int, set[str]],
) -> list[str]:
    """Return all PDF/hash/prompt join mismatches in ``rows``.

    The committed case-metrics table contains one prompt digest per case but
    not prompt text.  Stability across runs is therefore the strongest local
    prompt-join assertion available without re-materializing external prompts.
    """

    errors: list[str] = []
    for row in rows:
        number = int(row["case_number"])
        expected = manifest_by_number[number]
        if row["reference_pdf"] != expected["source_pdf"]:
            errors.append(f"case {number}: reference_pdf")
        if row["reference_sha256"].lower() != expected["source_sha256"].lower():
            errors.append(f"case {number}: reference_sha256")
        if row["prompt_sha256"] not in prompt_hashes[number]:
            errors.append(f"case {number}: prompt_sha256")
    return errors


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.add(str(key).lower())
            keys.update(_all_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_all_keys(item))
    return keys


def test_pdf_references_are_hash_addressed_without_committed_raw_pdf_leakage(
    artifacts: dict[str, Any],
) -> None:
    """Reference identity is present, while raw holdout PDFs stay external."""

    manifest = artifacts["manifest"]
    records = manifest["records"]
    assert manifest["version"] == "holdout-prompt-v2"
    assert manifest["count"] == EXPECTED_CASES
    assert len(records) == EXPECTED_CASES
    assert manifest["source_prompts_preserved"] is True

    pdf_names = [str(record["source_pdf"]) for record in records]
    pdf_hashes = [str(record["source_sha256"]).lower() for record in records]
    assert all(name.lower().endswith(".pdf") for name in pdf_names)
    assert all(SHA256.fullmatch(digest) for digest in pdf_hashes)
    assert len(pdf_names) == len(set(pdf_names)) == EXPECTED_CASES
    assert len(pdf_hashes) == len(set(pdf_hashes)) == EXPECTED_CASES

    report_pdf = HOLDOUT_ROOT / "report" / "benchmark-report.pdf"
    raw_pdfs = {
        path.relative_to(HOLDOUT_ROOT)
        for path in HOLDOUT_ROOT.rglob("*.pdf")
        if path != report_pdf
    }
    assert not raw_pdfs, (
        "raw holdout PDFs would make this checkout a leakage surface: "
        f"{sorted(str(path) for path in raw_pdfs)}"
    )
    assert report_pdf.is_file()

    forbidden = {"pdf_text", "extracted_text", "prompt_text", "ground_truth", "gold_answer"}
    assert not forbidden.intersection(_all_keys(manifest))


def test_manifest_and_reference_hash_controls_are_reproducible(
    artifacts: dict[str, Any],
) -> None:
    """Verify the published manifest digest and every local reference digest."""

    manifest = artifacts["manifest"]
    summary = artifacts["summary"]
    data_quality = summary["data_quality"]
    assert sha256_file(MANIFEST_PATH) == EXPECTED_MANIFEST_SHA256
    assert data_quality["prompt_manifest_sha256"] == EXPECTED_MANIFEST_SHA256
    assert SHA256.fullmatch(data_quality["reference_cache_sha256"])

    for record in manifest["records"]:
        source_sha = str(record["source_sha256"]).lower()
        assert SHA256.fullmatch(source_sha)
        assert source_sha != str(record["case_id"]).lower()

    # The cache digest is published, but the external cache itself is not in
    # this checkout; the test deliberately does not pretend to re-hash absent
    # bytes.
    assert not list(HOLDOUT_ROOT.rglob("*reference*.jsonl"))


def test_prompt_manifest_is_hash_only_and_prompt_digest_is_stable(
    artifacts: dict[str, Any],
) -> None:
    """Prompt text is external; the committed table carries only stable hashes."""

    manifest = artifacts["manifest"]
    rows = artifacts["rows"]
    records = manifest["records"]
    prompt_files = [str(record["prompt_file"]) for record in records]
    assert len(prompt_files) == len(set(prompt_files)) == EXPECTED_CASES
    assert all(Path(name).name == name for name in prompt_files)
    assert not any((HOLDOUT_ROOT / name).is_file() for name in prompt_files)

    headers = set(rows[0])
    assert "prompt_sha256" in headers
    assert "prompt" not in headers
    assert "prompt_text" not in headers
    assert "ground_truth" not in headers

    manifest_by_number = _manifest_by_number(manifest)
    prompt_hashes = _prompt_hashes_by_number(rows)
    assert set(prompt_hashes) == set(manifest_by_number)
    for number, hashes in prompt_hashes.items():
        assert len(hashes) == 1, f"prompt hash changed across runs for case {number}"
        digest = next(iter(hashes))
        assert SHA256.fullmatch(digest)
        assert digest != str(manifest_by_number[number]["source_sha256"]).lower()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("reference_pdf", "not-the-reference.pdf"),
        ("reference_sha256", "0" * 64),
        ("prompt_sha256", "f" * 64),
    ],
)
def test_adversarial_pdf_hash_and_prompt_join_mutations_are_rejected(
    artifacts: dict[str, Any], field: str, replacement: str
) -> None:
    """A single altered join key must be actionable rather than silently scored."""

    original = dict(artifacts["rows"][0])
    mutated = dict(original)
    mutated[field] = replacement
    manifest_by_number = _manifest_by_number(artifacts["manifest"])
    prompt_hashes = _prompt_hashes_by_number(artifacts["rows"])
    errors = _join_errors([mutated], manifest_by_number, prompt_hashes)
    assert errors == [f"case 1: {field}"]


def test_duplicates_and_invalid_joins_are_absent_from_committed_evidence(
    artifacts: dict[str, Any],
) -> None:
    """Manifest, catalog, and per-run metrics have unique join identities."""

    manifest = artifacts["manifest"]
    catalog = artifacts["catalog"]
    rows = artifacts["rows"]
    summary = artifacts["summary"]
    manifest_by_number = _manifest_by_number(manifest)
    prompt_hashes = _prompt_hashes_by_number(rows)

    assert not _join_errors(rows, manifest_by_number, prompt_hashes)
    assert all(item["invalid_reference_joins"] == 0 for item in summary["summaries"])

    run_ids = [str(run["case_id"]) for run in catalog["runs"]]
    assert len(run_ids) == len(set(run_ids)) == EXPECTED_RUNS

    for run_id, run_rows in _rows_by_run(rows).items():
        identities = [(run_id, int(row["case_number"])) for row in run_rows]
        assert len(identities) == len(set(identities)), f"duplicate row in {run_id}"
        assert {number for _, number in identities} == set(range(1, EXPECTED_CASES + 1))

    # Prove the duplicate guard is sensitive using a copy of a real identity;
    # no fixture or evidence file is generated.
    first_record = manifest["records"][0]
    duplicated_case_ids = [first_record["case_id"], first_record["case_id"]]
    assert len(duplicated_case_ids) != len(set(duplicated_case_ids))


def test_coverage_matches_status_rows_and_preserves_partial_run_separation(
    artifacts: dict[str, Any],
) -> None:
    """Missing rows count as zero coverage and cannot become a FULL ranking row."""

    summary_by_run = {item["case_id"]: item for item in artifacts["summary"]["summaries"]}
    rows_by_run = _rows_by_run(artifacts["rows"])
    assert set(summary_by_run) == set(rows_by_run)
    assert len(summary_by_run) == EXPECTED_RUNS

    for run_id, run_rows in rows_by_run.items():
        summary = summary_by_run[run_id]
        found = [row for row in run_rows if row["status"] != "MISSING"]
        succeeded = [row for row in run_rows if row["status"] == "SUCCEEDED"]
        failed = [
            row
            for row in run_rows
            if row["status"] not in {"SUCCEEDED", "MISSING"}
        ]
        missing = [row for row in run_rows if row["status"] == "MISSING"]
        assert int(summary["expected_cases"]) == EXPECTED_CASES
        assert int(summary["outputs_found"]) == len(found)
        assert int(summary["succeeded"]) == len(succeeded)
        assert int(summary["failed"]) == len(failed)
        assert int(summary["missing"]) == len(missing)
        assert float(summary["coverage"]) == pytest.approx(len(found) / EXPECTED_CASES)
        assert summary["comparable_full_run"] == (len(found) == EXPECTED_CASES)
        assert summary["invalid_reference_joins"] == 0

    partial = summary_by_run["C09"]
    assert int(partial["outputs_found"]) == 103
    assert int(partial["missing"]) == 897
    assert partial["comparable_full_run"] is False
    assert partial["quality_rank"] is None
    assert {
        int(row["case_number"])
        for row in rows_by_run["C09"]
        if row["status"] != "MISSING"
    } == set(range(1, 104))


def test_schema_contract_and_summary_disclose_ground_truth_limits(
    artifacts: dict[str, Any],
) -> None:
    """Schema controls and the non-ground-truth status are explicit."""

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["properties"]["schema_version"]["const"] == "benchmark-v2.result.v1"
    assert schema["properties"]["status"]["enum"] == ["FULL", "PARTIAL"]
    assert schema["properties"]["records"]["type"] == "array"
    assert schema["$defs"]["sha256"]["pattern"] == r"^[0-9a-fA-F]{64}$"
    assert set(schema["required"]) == {
        "schema_version",
        "run_id",
        "status",
        "metadata",
        "dimensions",
        "records",
    }

    summary = artifacts["summary"]
    assert summary["schema_version"] == "decree-factual-fidelity.v2"
    assert summary["reference"]["join"] == "case_number + reference_pdf + reference_sha256"
    assert "not ground truth" in summary["reference"]["prompt_role"].lower()
    assert summary["metric_contract"]["legal_metrics"] == "NOT_HUMAN_ADJUDICATED"
    assert not {"ground_truth", "gold_answer"}.intersection(_all_keys(summary))


def test_runtime_full_partial_contract_uses_real_case_ids() -> None:
    """Runtime validation rejects FULL under-counts and retains PARTIAL."""

    metadata = build_metadata(
        run_id="validation-contract-check",
        dataset_hash=EXPECTED_MANIFEST_SHA256,
        code_version="validation-test",
        generated_at_utc="2026-08-25T12:00:00Z",
        seed=20260825,
        dimensions={"source": "committed-holdout-metrics"},
    )
    rows = _read_case_rows()
    real_case_ids = [
        {"case_id": row["case_number"], "status": row["status"]}
        for row in rows
        if row["case_id"] == "C15" and row["status"] == "SUCCEEDED"
    ][:2]
    assert len(real_case_ids) == 2

    full = build_result(real_case_ids, metadata, expected_count=2)
    partial = build_result(real_case_ids[:1], metadata, expected_count=2, status="PARTIAL")
    assert full["status"] == "FULL"
    assert partial["status"] == "PARTIAL"
    with pytest.raises(ContractError, match="FULL result"):
        build_result(real_case_ids[:1], metadata, expected_count=2, status="FULL")
