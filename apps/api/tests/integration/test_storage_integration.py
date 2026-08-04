"""Storage integration tests using a disposable filesystem root."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage
from legal_ai.domain.errors import PathValidationError


@pytest.mark.integration
def test_storage_root_and_compensation_are_safe(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path / "exports")
    relative = storage.build_relative_path(
        UUID("22222222-2222-4222-8222-222222222222"),
        UUID("11111111-1111-4111-8111-111111111111"),
        "PDF",
        1,
    )
    temporary = storage.create_temp(relative)
    temporary.write_bytes(b"data")
    storage.atomic_replace(temporary, relative)
    storage.delete(relative)
    assert not storage.exists(relative)
    with pytest.raises(PathValidationError):
        storage.resolve_relative("../outside")


@pytest.mark.integration
def test_versions_are_distinct_and_path_contains_no_business_identity(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)
    first = storage.build_relative_path(
        UUID("22222222-2222-4222-8222-222222222222"),
        UUID("11111111-1111-4111-8111-111111111111"),
        "DOCX",
        1,
    )
    second = storage.build_relative_path(
        UUID("22222222-2222-4222-8222-222222222222"),
        UUID("11111111-1111-4111-8111-111111111111"),
        "DOCX",
        2,
    )
    assert first != second
    assert first.count("/") == second.count("/") == 4
    assert all(
        forbidden not in first.lower()
        for forbidden in ("actor", "case_number", "document_type", "2026")
    )
