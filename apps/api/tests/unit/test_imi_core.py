"""Unit tests for the isolated IMI Core adapter helpers."""

from inspect import getsource, signature

from legal_ai.adapters.database.imi_core import (
    ImiCoreRepository,
    _decode_variable_value,
)


def test_decode_variable_value_reads_json_string_values() -> None:
    assert _decode_variable_value('"01/09/2026"') == "01/09/2026"


def test_decode_variable_value_keeps_plain_values_and_handles_null() -> None:
    assert _decode_variable_value("texto sin JSON") == "texto sin JSON"
    assert _decode_variable_value(None) == ""


def test_create_case_file_accepts_optional_case_number_and_employee() -> None:
    parameters = signature(ImiCoreRepository.create_case_file).parameters

    assert parameters["case_number"].default is None
    assert parameters["employee_id"].annotation == "uuid.UUID | None"


def test_update_document_carries_template_values_to_new_version() -> None:
    source = getsource(ImiCoreRepository.update_document)

    assert "INSERT INTO imi.document_variable_values" in source
    assert "previous_version.version = :expected_version" in source
    assert "new_version.version = :new_version" in source
