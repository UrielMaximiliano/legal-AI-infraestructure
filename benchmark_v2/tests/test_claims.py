from __future__ import annotations

from benchmark_v2.evaluators.claims import (
    FN,
    FP,
    NOT_CALCULABLE,
    TP,
    evaluate,
    extract_atomic_claims,
    extract_contradictions,
    extract_legal_entities,
    score_claims,
    score_contradictions,
    score_entities,
)


def test_structured_gold_is_the_only_truth_source() -> None:
    prediction = {"claims": [{"id": "p1", "text": "El plazo es de 10 días."}]}
    gold = {"claims": [{"id": "g1", "text": "El plazo es de 30 días."}]}

    result = score_claims(prediction, gold)

    assert result["status"] == "CALCULATED"
    assert result["counts"] == {TP: 0, FP: 1, FN: 1, NOT_CALCULABLE: 0}
    assert {item["status"] for item in result["verdicts"]} == {FP, FN}


def test_missing_gold_is_not_calculable_and_not_zero() -> None:
    result = score_claims("El tribunal ordena pagar.", {})

    assert result["status"] == NOT_CALCULABLE
    assert result["tp"] is None
    assert result["fn"] is None
    assert result["counts"][NOT_CALCULABLE] == 1


def test_empty_gold_is_calculable_and_detects_invented_claim() -> None:
    result = score_claims("El tribunal ordena pagar.", {"claims": []})

    assert result["status"] == "CALCULATED"
    assert result["tp"] == 0
    assert result["fp"] == 1
    assert result["fn"] == 0
    assert result["precision"] == 0.0


def test_claim_extraction_splits_atomic_clauses_and_normalizes() -> None:
    claims = extract_atomic_claims(
        "El contrato obliga a pagar. La parte no puede rescindir y el tribunal ordena notificar."
    )

    assert len(claims) == 3
    assert claims[0]["polarity"] == "AFFIRMED"
    assert claims[1]["polarity"] == "NEGATED"
    assert claims[2]["predicate"] == "ordena"
    assert claims[0]["id"].startswith("claim-")


def test_legal_entity_extraction_and_structured_entity_scoring() -> None:
    entities = extract_legal_entities(
        "El Ministerio de Justicia dictó el Decreto N° 123/2024 ante el Juzgado Federal."
    )
    kinds = {entity["type"] for entity in entities}
    texts = {entity["normalized"] for entity in entities}

    assert "LEGAL_INSTRUMENT" in kinds
    assert "COURT" in kinds
    assert "ministerio de justicia" in texts
    result = score_entities(
        {"entities": [{"text": "Ministerio de Justicia", "type": "organization"}]},
        {"entities": [{"entity_id": "e1", "text": "Ministerio de Justicia", "type": "ORGANIZATION"}]},
    )
    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0


def test_contradictions_are_detected_only_for_same_proposition() -> None:
    text = "El plazo es de 10 días. El plazo es de 30 días. El tribunal ordena pagar."
    contradictions = extract_contradictions(text)

    assert len(contradictions) == 1
    assert "different object" in contradictions[0]["reason"]


def test_structured_contradictions_match_independently_of_pair_order() -> None:
    gold = {
        "contradictions": [
            {
                "id": "x1",
                "claim_a": {"subject": "plazo", "predicate": "es", "object": "10 días"},
                "claim_b": {"subject": "plazo", "predicate": "es", "object": "30 días"},
            }
        ]
    }
    prediction = {
        "contradictions": [
            {
                "claim_a": {"subject": "plazo", "predicate": "es", "object": "30 días"},
                "claim_b": {"subject": "plazo", "predicate": "es", "object": "10 días"},
            }
        ]
    }

    result = score_contradictions(prediction, gold)

    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0


def test_evaluate_reports_partial_when_gold_has_one_dimension() -> None:
    result = evaluate(
        "El contrato obliga a pagar.",
        {"claims": [{"text": "El contrato obliga a pagar."}]},
    )

    assert result["status"] == "PARTIAL"
    assert result["claims"]["tp"] == 1
    assert result["entities"]["status"] == NOT_CALCULABLE
    assert result["contradictions"]["status"] == NOT_CALCULABLE
