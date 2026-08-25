"""Unit tests for the benchmark-v2 legal-field evaluator."""

from __future__ import annotations

import pytest

from benchmark_v2.evaluators.legal_fields import (
    CORRECT,
    INVALID,
    MISSING,
    NOT_APPLICABLE,
    NOT_CALCULABLE,
    PARTIAL,
    LegalFieldsEvaluator,
    extract_legal_fields,
    score_field,
    score_legal_fields,
)

GOLD = {
    "norma": "Ley 27.610",
    "fecha": "15 de agosto de 2024",
    "plazo": "30 días",
    "expediente": "EX-2024-123456",
    "referencias": ["artículo 1", "artículo 2, inciso a"],
}


def test_default_fields_normalize_legal_spellings_and_are_exact() -> None:
    result = score_legal_fields(
        GOLD,
        {
            "norma": "LEY N° 27.610",
            "fecha": "15/08/2024",
            "plazo": "dentro de 30 dias",
            "expediente": "Expediente EX/2024/123456",
            "referencias": ["Art. 1", "ARTÍCULO 2, inciso A"],
        },
    )

    assert result["status"] == CORRECT
    assert result["coverage"] == 1.0
    assert result["accuracy"] == 1.0
    assert all(item["status"] == CORRECT for item in result["fields"].values())


def test_missing_and_invalid_are_distinct_and_reduce_coverage() -> None:
    result = score_legal_fields(
        GOLD,
        {
            "norma": "Ley 27.610",
            "fecha": "fecha desconocida",
            # plazo and expediente are intentionally absent
            "referencias": ["artículo 1"],
        },
    )

    assert result["fields"]["fecha"]["status"] == INVALID
    assert result["fields"]["plazo"]["status"] == MISSING
    assert result["fields"]["expediente"]["status"] == MISSING
    assert result["invalid_fields"] == ["fecha"]
    assert set(result["missing_fields"]) == {"plazo", "expediente"}
    assert result["coverage"] == pytest.approx(2 / 5)
    assert result["accuracy"] == pytest.approx((1 + 0 + 0 + 0 + 2 / 3) / 5)


def test_explicit_not_applicable_is_not_absence() -> None:
    result = score_legal_fields(
        {**GOLD, "plazo": {"applicable": False}},
        {"norma": GOLD["norma"], "fecha": GOLD["fecha"], "expediente": GOLD["expediente"], "referencias": GOLD["referencias"]},
    )

    field = result["fields"]["plazo"]
    assert field["status"] == NOT_APPLICABLE
    assert field["not_applicable"] is True
    assert field["missing"] is False
    assert result["not_applicable_fields"] == ["plazo"]
    assert result["applicable_fields"] == 4
    assert result["coverage"] == 1.0


def test_absent_gold_is_not_calculable_and_is_excluded() -> None:
    result = score_legal_fields({"norma": GOLD["norma"]}, {"norma": GOLD["norma"]})

    assert result["fields"]["norma"]["status"] == CORRECT
    assert result["fields"]["fecha"]["status"] == NOT_CALCULABLE
    assert result["fields"]["fecha"]["missing"] is False
    assert set(result["not_calculable_fields"]) == {"fecha", "plazo", "expediente", "referencias"}
    assert result["calculable_fields"] == 1
    assert result["accuracy"] == 1.0


def test_raw_text_prediction_is_extracted_into_typed_fields() -> None:
    text = (
        "Se aplica la Ley 27.610. La fecha es 15/08/2024 y el plazo es de 30 días. "
        "Expediente EX-2024-123456; conforme artículo 1."
    )
    extracted = extract_legal_fields(text)
    result = score_legal_fields(
        {**GOLD, "referencias": ["artículo 1"]},
        text,
    )

    assert extracted["norma"] == ["Ley 27.610"]
    assert result["accuracy"] == 1.0


def test_configurable_field_supports_validator_and_normalizer() -> None:
    result = score_legal_fields(
        {"monto": "ARS 1.000"},
        {"monto": "ars 1000"},
        fields={
            "monto": {
                "normalizer": lambda value: "".join(char for char in str(value).lower() if char.isalnum()),
                "validator": lambda value: isinstance(value, str) and bool(value.strip()),
            }
        },
    )

    assert result["fields"]["monto"]["status"] == CORRECT
    assert result["accuracy"] == 1.0


def test_reference_collection_reports_partial_f1() -> None:
    result = score_field(
        "referencias",
        ["artículo 1", "artículo 2"],
        ["art. 1"],
    )

    assert result["status"] == PARTIAL
    assert result["exact"] is False
    assert result["precision"] == 1.0
    assert result["recall"] == 0.5
    assert result["f1"] == pytest.approx(2 / 3)


def test_object_facade_and_aliases_use_the_same_contract() -> None:
    evaluator = LegalFieldsEvaluator(fields=("norma",))
    result = evaluator({"norma": "Ley 1"}, {"norma": "Ley 1"})

    assert result["fields"]["norma"]["status"] == CORRECT
    assert evaluator.score({"norma": "Ley 1"}, {"norma": "Ley 2"})["accuracy"] == 0.0
