"""Tests for the optional, informational benchmark runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.benchmark_004 import _measure, p95, run_benchmark

DATASET = Path(__file__).parents[1] / "fixtures" / "benchmark_004_dataset.json"


def test_dataset_contract_is_synthetic_and_fixed() -> None:
    value = json.loads(DATASET.read_text(encoding="utf-8"))
    assert value["dataset_version"] == "004-benchmark-v1"
    assert value["drafts"] == 100
    assert value["reviews"] == 100
    assert value["comments"] == 1000
    assert value["snapshot"]["bytes"] == 102400
    assert value["artifacts"]["docx"]["bytes"] == 1048576
    assert value["artifacts"]["pdf"]["bytes"] == 1048576
    assert value["pii"] is False
    assert "Authorization" not in DATASET.read_text(encoding="utf-8")


def test_p95_uses_task_nearest_rank() -> None:
    assert p95([float(index) for index in range(1, 101)]) == 95.0


def test_threshold_alert_is_informational() -> None:
    result = _measure("test", lambda: None, 0, 2, 0.001)
    assert result["alert"] is True
    assert result["threshold_passed"] is False


def test_runner_writes_results_and_keeps_alert_non_blocking(tmp_path: Path) -> None:
    output = tmp_path / "004.json"
    result = run_benchmark(DATASET, output, warmup=0, iterations=1)
    assert output.exists()
    assert result["informational"] is True
    assert set(result["results"]) == {
        "review",
        "preview",
        "acceptance_202",
        "download",
        "reconcile",
    }
    assert set(result["additional_metrics"]) == {"export_docx", "export_pdf"}
    assert result["protocol"]["acceptance_202_excludes_full_render"] is True


def test_runner_rejects_invalid_dataset(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"dataset_version": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError):
        run_benchmark(invalid, tmp_path / "result.json", warmup=0, iterations=1)
