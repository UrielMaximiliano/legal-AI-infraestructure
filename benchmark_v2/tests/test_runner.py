"""Integration tests for the dependency-light benchmark-v2 runner."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark_v2.data.io import write_jsonl
from benchmark_v2.scripts.run_benchmark import NOT_CALCULABLE, run_benchmark


def _case(case_id: str, *, candidate: str | None = None) -> dict[str, object]:
    row: dict[str, object] = {
        "case_id": case_id,
        "references": ["La Ley 27.610 dispone un plazo de 30 días."],
        "gold": {"claims": [{"text": "La Ley 27.610 dispone un plazo de 30 días."}]},
        "legal_fields": {"norma": "Ley 27.610", "plazo": "30 días"},
        "returned_ids": ["doc-1", "doc-2"],
        "relevant_ids": ["doc-1"],
        "rag_context": [{"id": "doc-1", "text": "La Ley 27.610 dispone un plazo de 30 días."}],
        "schema": {"type": "object", "required": ["answer"]},
        "expected_format": "json",
        "expected_citations": ["doc-1"],
    }
    if candidate is not None:
        row["candidate"] = candidate
    return row


def test_runner_writes_independent_dimensions_without_overall_score(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    write_jsonl(
        cases_path,
        [
            _case("case-1", candidate='{"answer":"La Ley 27.610 dispone un plazo de 30 días."}'),
            _case("case-2"),
        ],
    )

    output_dir = tmp_path / "run"
    summary = run_benchmark(
        cases_path,
        out_dir=output_dir,
        run_id="test-run",
        expected_count=2,
        seed=7,
        human_sample=1,
    )

    assert summary["status"] == "FULL"
    assert summary["overall_score"] is None
    assert summary["opaque_overall_score"] is False
    assert (output_dir / "metrics.jsonl").exists()
    assert (output_dir / "metrics.csv").exists()
    assert (output_dir / "run_manifest.json").exists()
    assert (output_dir / "human_eval_template.jsonl").exists()

    records = [json.loads(line) for line in (output_dir / "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert set(records[0]) >= {"semantic", "claims", "legal_fields", "retrieval", "faithfulness", "structure"}
    assert records[1]["structure"]["status"] == NOT_CALCULABLE

    human_rows = (output_dir / "human_eval_template.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(human_rows) == 1
    assert json.loads(human_rows[0])["reviewer_1"]["utility"] is None


def test_runner_missing_input_is_not_calculable_and_has_no_metrics(tmp_path: Path) -> None:
    summary = run_benchmark(
        tmp_path / "does-not-exist.jsonl",
        out_dir=tmp_path / "missing-run",
        expected_count=1000,
    )

    assert summary["status"] == NOT_CALCULABLE
    assert summary["observed_count"] == 0
    assert summary["overall_score"] is None
    assert "input_cases_not_found" in summary["not_calculable_reasons"][0]
    assert (tmp_path / "missing-run" / "metrics.jsonl").read_text(encoding="utf-8") == ""
