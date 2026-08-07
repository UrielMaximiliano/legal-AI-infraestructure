"""Contract-focused storage tests for the local adapter."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import pytest

from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage
from legal_ai.domain.errors import PathValidationError

CASE_ID = UUID("22222222-2222-4222-8222-222222222222")
DRAFT_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_deterministic_layout_and_atomic_rename(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    assert storage.health()
    relative = storage.build_relative_path(CASE_ID, DRAFT_ID, "PDF", 4)
    temporary = storage.create_temp(relative)
    temporary.write_bytes(b"artifact")
    storage.atomic_replace(temporary, relative)
    assert not temporary.exists()
    assert b"".join(storage.stream(relative, 2)) == b"artifact"


@pytest.mark.parametrize("path", ["/absolute.pdf", "../escape.pdf", "a\\b.pdf"])
def test_traversal_and_absolute_paths_are_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(PathValidationError):
        LocalArtifactStorage(tmp_path).resolve_relative(path)


def test_permissions_are_minimal_on_posix(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX permissions unavailable")
    storage = LocalArtifactStorage(tmp_path)
    relative = storage.build_relative_path(CASE_ID, DRAFT_ID, "DOCX", 1)
    temporary = storage.create_temp(relative)
    assert temporary.stat().st_mode & 0o777 == 0o600
    assert temporary.parent.stat().st_mode & 0o777 == 0o700
