"""Focused checks for configurable template parsing and preview."""

from legal_ai.application.template_management import (
    extract_file_content,
    fields_from_markers,
    marker_keys,
    normalize_blank_fields,
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


def test_blanks_use_line_label() -> None:
    assert normalize_blank_fields("Nombre: ____________") == "Nombre: {{nombre}}"
    assert normalize_blank_fields("Monto: $ ____________") == "Monto: $ {{monto}}"


def test_date_segments_group_into_single_marker() -> None:
    result = normalize_blank_fields("Fecha: ____/____/______")

    assert result == "Fecha: {{fecha}}"
    assert marker_keys(result) == ["fecha"]


def test_duplicate_labels_reuse_same_key() -> None:
    result = normalize_blank_fields("Nombre: ____________\nNombre: ____________")

    assert result == "Nombre: {{nombre}}\nNombre: {{nombre}}"
    assert marker_keys(result) == ["nombre"]


def test_fallback_campo_n_without_label_is_stable() -> None:
    result = normalize_blank_fields("____________\n____________")

    assert result == "{{campo_1}}\n{{campo_2}}"


def test_preserves_markers_and_does_not_convert_normal_text() -> None:
    body = "Expediente {{expediente}}.\nTexto normal sin blancos."
    assert normalize_blank_fields(body) == body

    preserved = normalize_blank_fields("Folio {{folio}}: ____________")
    assert "{{folio}}" in preserved
    assert "____________" not in preserved


def test_extract_docx_normalizes_body_and_blocks() -> None:
    from io import BytesIO

    from docx import Document

    document = Document()
    document.add_paragraph("Nombre: ____________")
    payload = BytesIO()
    document.save(payload)

    body, blocks, _warnings, _pages = extract_file_content(
        "plantilla.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        payload.getvalue(),
    )

    assert body == "Nombre: {{nombre}}"
    assert blocks[0]["content"] == "Nombre: {{nombre}}"
