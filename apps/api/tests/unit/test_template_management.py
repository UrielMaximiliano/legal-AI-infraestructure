"""Focused checks for configurable template parsing and preview."""

from legal_ai.application.template_management import (
    fields_from_markers,
    marker_keys,
    preview_document,
    suggestions_for_body,
)


def test_repeated_markers_create_one_field_in_first_seen_order() -> None:
    body = "Resolución {{expediente}}\n{{interesado}} y {{expediente}}"

    assert marker_keys(body) == ["expediente", "interesado"]
    assert [field["key"] for field in fields_from_markers(body)] == [
        "expediente",
        "interesado",
    ]


def test_preview_preserves_false_and_zero_values() -> None:
    document, errors, _warnings = preview_document(
        name="Prueba",
        document_type="resolucion",
        body="Monto: {{monto}}; Activo: {{activo}}",
        fields=[
            {"key": "monto", "label": "Monto", "type": "number"},
            {"key": "activo", "label": "Activo", "type": "boolean"},
        ],
        rules=[],
        blocks=None,
        values={"monto": "0", "activo": "false"},
    )

    assert errors == []
    assert "Monto: 0" in document["content"]
    assert "Activo: False" in document["content"]


def test_placeholder_suggestions_group_occurrences() -> None:
    suggestions = suggestions_for_body(
        "Firmante: ____________\nRepite: ____________", fields=[]
    )

    assert len(suggestions) == 1
    assert len(suggestions[0]["occurrences"]) == 2
