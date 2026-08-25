"""Unit tests for the reproducible Benchmark v2 statistics layer."""

from __future__ import annotations

import pytest

from benchmark_v2.statistics import (
    bootstrap_ci,
    case_statistics,
    delta_full_partial,
    paired_bootstrap,
    render_markdown_table,
    sensitivity_tests,
    statistics_table,
    summarize,
)


def test_summarize_publishes_mean_and_median_without_opaque_score() -> None:
    result = summarize([1.0, 2.0, 8.0])

    assert result["n"] == 3
    assert result["mean"] == pytest.approx(11 / 3)
    assert result["median"] == 2.0
    assert result["ci_low"] <= result["mean"] <= result["ci_high"]
    assert "overall" not in result
    assert "overall_score" not in result


def test_paired_bootstrap_is_seeded_and_resamples_pairs() -> None:
    left = [0.90, 0.40, 0.80, 0.10]
    right = [0.80, 0.50, 0.60, 0.20]

    first = paired_bootstrap(
        left, right, seed=1234, n_resamples=400, return_distribution=True
    )
    second = paired_bootstrap(
        left, right, seed=1234, n_resamples=400, return_distribution=True
    )
    changed = paired_bootstrap(
        left, right, seed=1235, n_resamples=400, return_distribution=True
    )

    assert first == second
    assert first["delta"] == pytest.approx(0.025)
    assert first["mean_delta"] == pytest.approx(0.025)
    assert first["paired"] is True
    assert first["resampling_unit"] == "case"
    assert first["seed"] == 1234
    assert first["method"] in {"bca", "percentile"}
    assert changed["bootstrap_distribution"] != first["bootstrap_distribution"]


def test_bca_falls_back_to_documented_percentile_for_one_case() -> None:
    result = bootstrap_ci([0.5], seed=8, n_resamples=200, method="bca")

    assert result["method"] == "percentile"
    assert result["requested_method"] == "bca"
    assert result["fallback_reason"]
    assert result["ci_low"] == result["ci_high"] == 0.5


def test_full_minus_partial_aligns_shared_cases_and_counts_exclusions() -> None:
    full = {
        "run_id": "full-1",
        "status": "FULL",
        "expected_count": 3,
        "records": [
            {"case_id": "c1", "score": 0.90},
            {"case_id": "c2", "score": 0.60},
            {"case_id": "c3", "score": 0.20},
        ],
    }
    partial = {
        "run_id": "partial-1",
        "status": "PARTIAL",
        "expected_count": 3,
        "records": [
            {"case_id": "c2", "score": 0.50},
            {"case_id": "c3", "score": 0.10},
        ],
    }

    result = delta_full_partial(full, partial, seed=7, n_resamples=300)

    assert result["comparison"] == "FULL-PARTIAL"
    assert result["full_status"] == "FULL"
    assert result["partial_status"] == "PARTIAL"
    assert result["paired_case_ids"] == ["c2", "c3"]
    assert result["paired_case_count"] == 2
    assert result["full_excluded_case_count"] == 1
    assert result["partial_excluded_case_count"] == 0
    assert result["delta"] == pytest.approx(0.10)
    assert result["direction"].startswith("positive")


def test_case_statistics_and_table_keep_metrics_separate() -> None:
    run = {
        "run_id": "run-1",
        "status": "FULL",
        "expected_count": 2,
        "records": [
            {"case_id": "c1", "accuracy": 1.0, "recall": 0.5},
            {"case_id": "c2", "accuracy": 0.5, "recall": 1.0},
        ],
    }

    summaries = case_statistics(run)
    table = statistics_table({"run-1": run})
    markdown = render_markdown_table(table)

    assert {row["metric"] for row in summaries} == {"accuracy", "recall"}
    assert {row["metric"] for row in table} == {"accuracy", "recall"}
    assert all("overall" not in row and "overall_score" not in row for row in table)
    assert "| metric |" in markdown
    assert "overall" not in markdown.lower()


def test_opaque_overall_metric_is_rejected() -> None:
    run = {"records": [{"case_id": "c1", "overall": 0.8}]}

    with pytest.raises(ValueError, match="opaque overall"):
        statistics_table({"run": run})


def test_sensitivity_reports_robust_diagnostics() -> None:
    result = sensitivity_tests(
        [0.95, 0.90, 0.20, 0.80, 0.75],
        [0.85, 0.80, 0.30, 0.70, 0.65],
        seed=99,
        n_resamples=250,
    )

    assert result["mean_delta"] == pytest.approx(0.06)
    assert "sign_test" in result
    assert "wilcoxon" in result
    assert "leave_one_case_out" in result
    assert result["resampling_unit"] == "case"


def test_bootstrap_requires_explicit_integer_seed() -> None:
    with pytest.raises(TypeError, match="explicit integer"):
        paired_bootstrap([1.0, 2.0], [0.0, 1.0], seed=None)  # type: ignore[arg-type]


def test_bootstrap_rejects_mismatched_pairs() -> None:
    with pytest.raises(ValueError, match="equal lengths"):
        paired_bootstrap([1.0, 2.0], [0.0], seed=1, n_resamples=20)
