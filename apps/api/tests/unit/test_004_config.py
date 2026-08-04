"""Configuration boundary tests for 004."""

import pytest
from pydantic import ValidationError

from legal_ai.config import ExportConfig


def test_relative_storage_root_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ExportConfig(EXPORT_STORAGE_ROOT="relative/exports")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("DOCX_GENERATION_TIMEOUT_SECONDS", 0),
        ("PDF_GENERATION_TIMEOUT_SECONDS", 0),
        ("MAX_PAGE_SIZE", 101),
        ("EXPORT_FAILED_ATTEMPT_RETENTION_DAYS", 0),
    ],
)
def test_invalid_export_limits_are_rejected(field: str, value: int) -> None:
    with pytest.raises((ValidationError, ValueError)):
        ExportConfig(**{field: value})


def test_absolute_storage_root_and_exact_maximum_are_accepted(tmp_path) -> None:
    config = ExportConfig(
        EXPORT_STORAGE_ROOT=tmp_path,
        MAX_FINALIZATION_NOTES_LENGTH=2000,
        MAX_PAGE_SIZE=100,
    )
    assert config.storage_root == tmp_path
    assert config.max_page_size == 100
