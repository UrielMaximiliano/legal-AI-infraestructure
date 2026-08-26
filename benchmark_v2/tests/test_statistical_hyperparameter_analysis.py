from __future__ import annotations

import math

from benchmark_v2.scripts.compute_statistical_hyperparameter_analysis import (
    binary_metric_mcnemar,
    cohen_dz,
    dominates,
    exact_mcnemar,
    holm,
    paired_bootstrap,
    select_representative,
    spearman,
    wilson,
)


def test_wilson_matches_c12_example() -> None:
    low, high = wilson(90, 1000)
    assert math.isclose(low, 0.07379614931508309, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(high, 0.1093417926430721, rel_tol=0, abs_tol=1e-12)


def test_exact_mcnemar_matches_c12_vs_c03_example() -> None:
    result = exact_mcnemar([True] * 49 + [False] * 18, [False] * 49 + [True] * 18)
    assert result["b_a_pass_b_fail"] == 49
    assert result["c_a_fail_b_pass"] == 18
    assert math.isclose(result["p_value"], 0.00019429778641481447, rel_tol=0, abs_tol=1e-15)


def test_holm_adjustment() -> None:
    assert holm([0.01, 0.04, 0.20]) == [0.03, 0.08, 0.2]


def test_paired_bootstrap_is_reproducible() -> None:
    left = paired_bootstrap([1.0, 0.0, 1.0, 0.0], seed=7, resamples=100)
    right = paired_bootstrap([1.0, 0.0, 1.0, 0.0], seed=7, resamples=100)
    assert left == right
    assert left["n"] == 4
    assert left["resamples"] == 100


def test_binary_unsupported_addition_uses_mcnemar() -> None:
    def item(free: bool, case_id: int) -> dict:
        return {
            "case_id": str(case_id),
            "unsupported_additions": {"critical_count": 0 if free else 1},
        }

    left = [item(value, index) for index, value in enumerate([True, True, False, False])]
    right = [item(value, index) for index, value in enumerate([True, False, True, False])]
    result = binary_metric_mcnemar(left, right, "unsupported_addition_free")
    assert result["b_a_pass_b_fail"] == 1
    assert result["c_a_fail_b_pass"] == 1
    assert result["discordant"] == 2
    assert result["test"] == "McNemar exact two-sided"


def test_cohen_dz_and_spearman() -> None:
    assert math.isclose(cohen_dz([1.0, 2.0, 3.0]), 2.0, rel_tol=0, abs_tol=1e-12)
    assert spearman([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == -1.0


def test_kappa_formula_for_c02_c14_example() -> None:
    n11, n00, n = 60, 904, 1000
    observed = (n11 + n00) / n
    pa, pb = 62 / n, 70 / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    kappa = (observed - expected) / (1 - expected)
    assert math.isclose(kappa, 0.7080765488160882, rel_tol=0, abs_tol=1e-12)


def test_pareto_dominance_and_canonical_selection() -> None:
    objectives = ("legal_pass", "claims")
    assert dominates({"legal_pass": 0.10, "claims": 0.8}, {"legal_pass": 0.09, "claims": 0.8}, objectives)
    assert not dominates({"legal_pass": 0.10, "claims": 0.7}, {"legal_pass": 0.09, "claims": 0.8}, objectives)
    members = [{"run": "C02"}, {"run": "C14"}]
    assert select_representative(members)["run"] == "C02"
    assert select_representative(members, "C14")["run"] == "C14"
