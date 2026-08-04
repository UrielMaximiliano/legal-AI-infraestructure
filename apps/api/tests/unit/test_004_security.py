"""004 security regression tests for storage, integrity and public surfaces."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import pytest

from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage
from legal_ai.application.artifact_integrity import (
    DOCX_MIME,
    ArtifactIntegrityValidator,
)
from legal_ai.domain.errors import PathValidationError

CASE_ID = UUID("22222222-2222-4222-8222-222222222222")
DRAFT_ID = UUID("11111111-1111-4111-8111-111111111111")
FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_storage_rejects_traversal_absolute_and_symlink_segments(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path / "root")
    for value in ("/etc/passwd", "../escape", "a\\b.docx"):
        with pytest.raises(PathValidationError):
            storage.resolve_relative(value)
    relative = storage.build_relative_path(CASE_ID, DRAFT_ID, "DOCX", 1)
    storage.create_temp(relative)
    if os.name != "nt":
        link = storage.root / str(CASE_ID)
        link.unlink() if link.is_symlink() else None
        outside = tmp_path / "outside"
        outside.mkdir()
        link.symlink_to(outside, target_is_directory=True)
        with pytest.raises(PathValidationError):
            storage.resolve_relative(relative)


def test_storage_filename_is_deterministic_and_contains_no_pii(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path / "root")
    relative = storage.build_relative_path(CASE_ID, DRAFT_ID, "PDF", 7)
    assert relative.endswith(f"/{DRAFT_ID}_v7.pdf")
    assert "case_number" not in relative
    assert "actor" not in relative


def test_fixture_docx_is_valid_and_does_not_expose_metadata(tmp_path: Path) -> None:
    digest = ArtifactIntegrityValidator().validate_docx(
        FIXTURES / "valid_document.docx", declared_mime=DOCX_MIME
    )
    assert len(digest) == 64
    assert "storage_path" not in (FIXTURES / "valid_document.docx").name
