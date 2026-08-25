from __future__ import annotations

import math

from benchmark_v2.evaluators.semantic import (
    BERTScoreConfig,
    BERTScoreEvaluator,
    CALCULATED,
    NOT_CALCULABLE,
    chrf_score,
    evaluate_case,
    evaluate_cases,
    normalize_text,
    rouge_l_score,
)


def test_normalization_is_explicit_and_preserves_legal_punctuation() -> None:
    assert normalize_text("  Art.\u00a01\nNO  aplica  ") == "art. 1 no aplica"


def test_rouge_l_is_lcs_f1_and_deterministic() -> None:
    assert math.isclose(rouge_l_score("a b c", "a c"), 0.8)
    assert rouge_l_score("Artículo 1", "artículo 1") == 1.0


def test_chrf_is_bounded_and_case_normalized() -> None:
    assert chrf_score("Ley 1", " ley 1 ") == 1.0
    assert chrf_score("abc", "xyz") == 0.0
    assert 0.0 <= chrf_score("artículo 1", "artículo 2") <= 1.0


def test_missing_reference_is_not_calculable_and_does_not_become_zero() -> None:
    result = evaluate_case({"case_id": "c-1", "candidate": "respuesta"})
    assert result["status"] == NOT_CALCULABLE
    assert result["rouge_l"]["score"] is None
    assert result["chrf"]["score"] is None
    assert result["bertscore"]["score"] is None


def test_empty_reference_is_not_calculable_but_empty_candidate_is_a_score() -> None:
    missing = evaluate_case(
        {"case_id": "c-1", "candidate": "respuesta", "references": ["   "]}
    )
    assert missing["status"] == NOT_CALCULABLE
    calculated = evaluate_case(
        {"case_id": "c-2", "candidate": "", "references": ["referencia"]}
    )
    assert calculated["status"] == CALCULATED
    assert calculated["rouge_l"]["score"] == 0.0
    assert calculated["chrf"]["score"] == 0.0


def test_multiple_references_select_maximum_with_stable_first_tie() -> None:
    result = evaluate_case(
        {
            "case_id": "c-1",
            "candidate": "la respuesta",
            "references": ["otra", "la respuesta"],
        }
    )
    assert result["reference_count"] == 2
    assert result["rouge_l"]["reference_index"] == 1
    assert result["chrf"]["reference_index"] == 1


def test_bertscore_optional_degradation_is_explicit(monkeypatch) -> None:
    evaluator = BERTScoreEvaluator(
        config=BERTScoreConfig(model_type="test-model", lang="es")
    )
    monkeypatch.setattr(evaluator, "_get_score_fn", lambda: None)
    result = evaluator.score("respuesta", "referencia")
    assert result["status"] == NOT_CALCULABLE
    assert result["score"] is None
    assert "optional_dependency_missing" in result["reason"]


def test_bertscore_adapter_is_injectable_and_normalized() -> None:
    calls: list[tuple[list[str], list[str], dict[str, object]]] = []

    def fake_score(candidates: list[str], references: list[str], **kwargs: object):
        calls.append((candidates, references, kwargs))
        return ([0.7], [0.8], [0.75])

    evaluator = BERTScoreEvaluator(score_fn=fake_score)
    result = evaluate_case(
        {
            "case_id": "c-1",
            "candidate": "  RESPUESTA  ",
            "references": ["Referencia"],
        },
        bertscore=evaluator,
    )
    assert result["bertscore"]["status"] == CALCULATED
    assert result["bertscore"]["f1"] == 0.75
    assert calls == [
        (
            ["respuesta"],
            ["referencia"],
            {
                "model_type": "bert-base-multilingual-cased",
                "lang": "es",
                "idf": False,
                "rescale_with_baseline": False,
                "verbose": False,
            },
        )
    ]


def test_evaluate_cases_preserves_input_order_without_aggregate_invention() -> None:
    rows = evaluate_cases(
        [
            {"case_id": "b", "candidate": "x", "references": ["x"]},
            {"case_id": "a", "candidate": "y", "references": ["y"]},
        ],
        bertscore=BERTScoreEvaluator(
            score_fn=lambda *args, **kwargs: ([1.0], [1.0], [1.0])
        ),
    )
    assert [row["case_id"] for row in rows] == ["b", "a"]
    assert all("summary" not in row for row in rows)


def test_invalid_case_contract_never_coerces_missing_text() -> None:
    result = evaluate_case({"case_id": "c-1", "candidate": None, "references": ["ref"]})
    assert result["status"] == NOT_CALCULABLE
    assert result["reason"] == "candidate must be a string"
