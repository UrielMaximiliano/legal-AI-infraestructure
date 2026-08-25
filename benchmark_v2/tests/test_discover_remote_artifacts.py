from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

SnapshotBuilder = Callable[[Path], Path]


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _case_payload(number: int, external_id: str) -> dict[str, object]:
    return {
        "case_number": number,
        "external_id": external_id,
        "status": "SUCCEEDED",
        "http_status": 201,
        "rag_run_id": f"rag-{number}",
        "reference_pdf": f"{external_id}.pdf",
        "reference_sha256": _sha(external_id),
        "retrieved": 24,
        "selected": 20,
    }


def _manifest_row(number: int, external_id: str) -> str:
    return (
        f"HOLDOUT-{number:04d},prompt-{number:04d}-{external_id}.md,"
        f"{external_id}.pdf,{_sha(external_id)},3,4022,1394/2012,ORG,objeto,6,3,PASS"
    )


def _summary_row(number: int, external_id: str) -> str:
    return (
        f"{number},{external_id},SUCCEEDED,201,rag-{number},24,20,874,8134,9008,"
    )


SUMMARY_HEADER = (
    "case_number,external_id,status,http_status,rag_run_id,retrieved,"
    "selected,retrieval_ms,generation_ms,total_ms,error_code"
)

EXTERNAL_IDS = ("200001", "200002", "200003")


def build_snapshot(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.csv").write_text(
        "case_id,prompt_file,source_pdf,source_sha256,pages,extracted_chars,"
        "target_identifier_redacted,organization,objective,facts,"
        "operative_requirements,quality_status\n"
        + "\n".join(
            _manifest_row(index + 1, external)
            for index, external in enumerate(EXTERNAL_IDS)
        )
        + "\n",
        encoding="utf-8",
    )
    gold_lines = [
        json.dumps(
            {
                "reference_pdf": f"{external}.pdf",
                "reference_sha256": _sha(external),
                "facts": [{"fact_id": "organismo", "field": "organismo", "text": "ORG"}],
            }
        )
        for external in EXTERNAL_IDS
    ]
    (root / "pdf-gold-facts.auto.jsonl").write_text(
        "\n".join(gold_lines) + "\n", encoding="utf-8"
    )
    (root / "prompt-0001-200001.md").write_text("# prompt\n", encoding="utf-8")

    run_dir = root / "benchmark-mini-v1"
    run_dir.mkdir()
    configuration = {
        "run_id": "mini-v1",
        "requested_cases": 3,
        "start_case": 1,
        "top_k": 8,
        "minimum_score": 0.0,
        "api_base_url": "http://127.0.0.1:8000",
        "started_at": "2026-08-14T14:09:56+00:00",
        "execution": "sequential_monoslot",
    }
    (run_dir / "configuration.json").write_text(
        json.dumps(configuration), encoding="utf-8"
    )
    experiment = {
        "id": "caso-mini-v1",
        "embedding_model": "qwen3-embedding:4b-q4_K_M",
        "dimensions": 2560,
        "ollama_context_length": 32768,
        "rag_context_tokens": 8192,
        "rag_context_bytes": 65536,
        "output_tokens": 3072,
    }
    (run_dir / "experiment.yml").write_text(json.dumps(experiment), encoding="utf-8")
    progress = {"completed": 3, "succeeded": 3, "failed": 0, "total": 3}
    (run_dir / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    results = [
        json.dumps(_case_payload(index + 1, external))
        for index, external in enumerate(EXTERNAL_IDS)
    ]
    (run_dir / "results.jsonl").write_text("\n".join(results) + "\n", encoding="utf-8")
    (run_dir / "summary.csv").write_text(
        SUMMARY_HEADER + "\n" + "\n".join(
            _summary_row(index + 1, external)
            for index, external in enumerate(EXTERNAL_IDS)
        ) + "\n",
        encoding="utf-8",
    )
    (run_dir / "runner.log").write_text(
        "case=001 status=SUCCEEDED completed=1/3 total_ms=100\n"
        "case=003 status=SUCCEEDED completed=3/3 total_ms=300\n",
        encoding="utf-8",
    )
    cases_dir = run_dir / "cases"
    cases_dir.mkdir()
    for index, external in enumerate(EXTERNAL_IDS):
        number = index + 1
        (cases_dir / f"case-{number:04d}.json").write_text(
            json.dumps(_case_payload(number, external)), encoding="utf-8"
        )
    failed_dir = run_dir / "failed-attempts" / "attempt-1"
    failed_dir.mkdir(parents=True)
    (failed_dir / "note.txt").write_text("empty attempt", encoding="utf-8")
    return root


def inventory_of(dra, snapshot: Path):
    return dra.build_inventory(snapshot, snapshot.parent / "out", 5)


def issue_codes(dra, snapshot: Path) -> set[str]:
    inventory, _ = inventory_of(dra, snapshot)
    reconciliation = inventory["reconciliation"]
    assert isinstance(reconciliation, dict)
    issues = reconciliation["issues"]
    assert isinstance(issues, list)
    return {str(issue["code"]) for issue in issues}


def test_consistent_snapshot_has_zero_findings(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    inventory, markdown = inventory_of(dra, snapshot)
    reconciliation = inventory["reconciliation"]
    assert isinstance(reconciliation, dict)
    assert reconciliation["verdict"] == "CONSISTENT"
    assert reconciliation["issue_count"] == 0
    run = inventory["runs"][0]
    assert isinstance(run, dict)
    counts = run["counts"]
    assert counts["case_files"] == 3
    assert counts["result_records"] == 3
    assert counts["summary_rows"] == 3
    assert run["status_distribution"] == {"SUCCEEDED": 3}
    linkage = run["manifest_linkage"]
    assert linkage == {
        "checked": True,
        "shared_case_numbers": 3,
        "pdf_name_mismatches": 0,
        "sha256_mismatches": 0,
    }
    manifest = inventory["top_level_files"]["manifest"]
    assert manifest["rows"] == 3
    assert manifest["quality_status_counts"] == {"PASS": 3}
    assert "# Inventario de artefactos remotos — benchmark v2" in markdown
    assert "**CONSISTENT**" in markdown


def test_missing_case_file_is_reported(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    (snapshot / "benchmark-mini-v1" / "cases" / "case-0002.json").unlink()
    codes = issue_codes(dra, snapshot)
    assert "CASE_FILES_MISSING" in codes


def test_unexpected_case_file_is_reported(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    payload = _case_payload(9, "200009")
    target = snapshot / "benchmark-mini-v1" / "cases" / "case-0009.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    codes = issue_codes(dra, snapshot)
    assert "CASE_FILES_UNEXPECTED" in codes


def test_cross_source_status_mismatch_is_reported(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    summary = snapshot / "benchmark-mini-v1" / "summary.csv"
    text = summary.read_text(encoding="utf-8")
    summary.write_text(text.replace("200002,SUCCEEDED", "200002,FAILED"), encoding="utf-8")
    codes = issue_codes(dra, snapshot)
    assert "CROSS_SOURCE_MISMATCH" in codes


def test_gold_facts_hash_mismatch_is_reported(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    gold = snapshot / "pdf-gold-facts.auto.jsonl"
    lines = gold.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["reference_sha256"] = _sha("tampered")
    lines[0] = json.dumps(record)
    gold.write_text("\n".join(lines) + "\n", encoding="utf-8")
    codes = issue_codes(dra, snapshot)
    assert "GOLD_FACTS_SHA256_MISMATCH" in codes


def test_gold_facts_coverage_gap_is_reported(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    gold = snapshot / "pdf-gold-facts.auto.jsonl"
    lines = gold.read_text(encoding="utf-8").splitlines()[:2]
    gold.write_text("\n".join(lines) + "\n", encoding="utf-8")
    codes = issue_codes(dra, snapshot)
    assert "GOLD_FACTS_COVERAGE_GAP" in codes


def test_manifest_duplicates_and_bad_ids_are_reported(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    manifest = snapshot / "manifest.csv"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    lines.append(lines[1])
    lines.append(lines[2].replace("HOLDOUT-0002", "BAD-ID"))
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    codes = issue_codes(dra, snapshot)
    assert "MANIFEST_DUPLICATE_CASE_NUMBERS" in codes
    assert "MANIFEST_IDS_UNPARSEABLE" in codes


def test_progress_count_mismatch_is_reported(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    progress_path = snapshot / "benchmark-mini-v1" / "progress.json"
    progress_path.write_text(
        json.dumps({"completed": 5, "succeeded": 4, "failed": 0, "total": 3}),
        encoding="utf-8",
    )
    codes = issue_codes(dra, snapshot)
    assert "PROGRESS_COUNT_MISMATCH" in codes
    assert "PROGRESS_SUM_MISMATCH" in codes


def test_duplicate_and_invalid_result_lines_are_reported(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    results = snapshot / "benchmark-mini-v1" / "results.jsonl"
    lines = results.read_text(encoding="utf-8").splitlines()
    results.write_text("\n".join([*lines, lines[0], "not-json"]) + "\n", encoding="utf-8")
    codes = issue_codes(dra, snapshot)
    assert "DUPLICATE_RESULT_NUMBERS" in codes
    assert "RESULTS_LINES_INVALID" in codes


def test_unparseable_case_file_is_reported(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    broken = snapshot / "benchmark-mini-v1" / "cases" / "case-0002.json"
    broken.write_text("{not json", encoding="utf-8")
    codes = issue_codes(dra, snapshot)
    assert "CASE_FILES_UNPARSEABLE" in codes


def test_bom_prefixed_csv_files_reconcile_cleanly(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    for relative in ("manifest.csv", "benchmark-mini-v1/summary.csv"):
        path = snapshot / relative
        raw = path.read_bytes()
        path.write_bytes(b"\xef\xbb\xbf" + raw)
    codes = issue_codes(dra, snapshot)
    assert not codes


def test_flat_yaml_experiment_fallback_is_parsed(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    experiment = snapshot / "benchmark-mini-v1" / "experiment.yml"
    experiment.write_text(
        "id: caso-yaml-fallback\n"
        "embedding_model: qwen3-embedding:4b-q4_K_M\n"
        "dimensions: 2560\n"
        "# comment line\n"
        "\n",
        encoding="utf-8",
    )
    inventory, _ = inventory_of(dra, snapshot)
    detail = inventory["runs"][0]["experiment"]
    assert detail["id"] == "caso-yaml-fallback"
    assert detail["dimensions"] == 2560


def test_missing_manifest_is_fatal_for_coverage_but_not_for_runs(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    (snapshot / "manifest.csv").unlink()
    codes = issue_codes(dra, snapshot)
    assert "MANIFEST_MISSING" in codes
    inventory, _ = inventory_of(dra, snapshot)
    notes = inventory["reconciliation"]["notes"]
    assert any("coverage cannot be verified" in note for note in notes)
    runs = inventory["runs"]
    assert runs[0]["manifest_linkage"] == {"checked": False}


def test_cli_exit_codes_and_read_only_root(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    output_dir = tmp_path / "inventory"

    def tree_state(root: Path) -> set[tuple[str, int]]:
        return {
            (str(path.relative_to(root)), path.stat().st_size)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    before = tree_state(snapshot)
    exit_code = dra.main(
        [str(snapshot), "--output-dir", str(output_dir)]
    )
    after = tree_state(snapshot)
    assert exit_code == 0
    assert before == after
    assert (output_dir / "artifact_inventory.json").is_file()
    assert (output_dir / "artifact_inventory.md").is_file()

    summary = snapshot / "benchmark-mini-v1" / "summary.csv"
    text = summary.read_text(encoding="utf-8")
    summary.write_text(text.replace("200003,SUCCEEDED", "200003,FAILED"), encoding="utf-8")
    assert dra.main([str(snapshot), "--output-dir", str(output_dir)]) == 1

    assert dra.main([str(tmp_path / "missing-root"), "--output-dir", str(output_dir)]) == 2
    inside_output = snapshot / "inside"
    assert dra.main([str(snapshot), "--output-dir", str(inside_output)]) == 2


def test_cli_custom_names_are_respected(dra, tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path / "remote")
    output_dir = tmp_path / "inventory-custom"
    exit_code = dra.main(
        [
            str(snapshot),
            "--output-dir",
            str(output_dir),
            "--json-name",
            "inv.json",
            "--markdown-name",
            "inv.md",
        ]
    )
    assert exit_code == 0
    assert (output_dir / "inv.json").is_file()
    assert (output_dir / "inv.md").is_file()
