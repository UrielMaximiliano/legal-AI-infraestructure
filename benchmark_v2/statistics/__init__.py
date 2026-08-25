"""Auditable, reproducible statistics for Benchmark v2.

Public functions use cases as the resampling unit, require an explicit seed for
bootstrap intervals, and publish each metric independently.  In particular,
there is no implicit or opaque ``overall`` score.
"""

from .core import (
    DEFAULT_CONFIDENCE_LEVEL,
    DEFAULT_RESAMPLES,
    bootstrap_ci,
    build_statistics_table,
    case_statistics,
    compare_paired,
    compare_runs,
    delta_full_partial,
    describe,
    full_partial_delta,
    paired_bootstrap,
    paired_delta,
    per_case_table,
    render_markdown_table,
    sensibility_tests,
    sensitivity_tests,
    statistics_table,
    summarise,
    summarize,
)

__all__ = [
    "DEFAULT_CONFIDENCE_LEVEL",
    "DEFAULT_RESAMPLES",
    "bootstrap_ci",
    "build_statistics_table",
    "case_statistics",
    "compare_paired",
    "compare_runs",
    "delta_full_partial",
    "describe",
    "full_partial_delta",
    "paired_bootstrap",
    "paired_delta",
    "per_case_table",
    "render_markdown_table",
    "sensibility_tests",
    "sensitivity_tests",
    "statistics_table",
    "summarise",
    "summarize",
]
