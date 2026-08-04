"""Filesystem/integrity integration checks that require no database state."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage


@pytest.mark.integration
def test_publish_and_stream_are_same_directory_atomic_operations(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)
    relative = storage.build_relative_path(
        UUID("22222222-2222-4222-8222-222222222222"),
        UUID("11111111-1111-4111-8111-111111111111"),
        "PDF",
        1,
    )
    temporary = storage.create_temp(relative)
    temporary.write_bytes(b"%PDF-1.7\n%%EOF")
    storage.atomic_replace(temporary, relative)
    assert not temporary.exists()
    assert b"".join(storage.stream(relative, 4)).endswith(b"%%EOF")
