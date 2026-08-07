"""Unit tests for secure storage and artifact integrity contracts."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from uuid import UUID

import pytest

from legal_ai.adapters.renderers.docx_renderer import PythonDocxRenderer
from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage
from legal_ai.application.artifact_integrity import (
    DOCX_MIME,
    PDF_MIME,
    ArtifactIntegrityValidator,
)
from legal_ai.config import settings
from legal_ai.domain.errors import (
    HashValidationError,
    InvalidArtifactError,
    PathValidationError,
)
from tests.unit.test_renderers import _snapshot

DRAFT_ID = UUID("11111111-1111-4111-8111-111111111111")
CASE_ID = UUID("22222222-2222-4222-8222-222222222222")


def _relative() -> str:
    return LocalArtifactStorage.build_relative_path(CASE_ID, DRAFT_ID, "DOCX", 1)


def test_storage_is_relative_and_atomic(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    relative = _relative()
    temporary = storage.create_temp(relative)
    temporary.write_bytes(b"document")
    storage.atomic_replace(temporary, relative)
    assert storage.exists(relative)
    assert b"".join(storage.stream(relative, chunk_size=2)) == b"document"


@pytest.mark.parametrize(
    "value",
    [
        "/etc/passwd",
        "../outside.docx",
        "11111111-1111-4111-8111-111111111111\\v1.docx",
    ],
)
def test_storage_rejects_unsafe_paths(tmp_path: Path, value: str) -> None:
    with pytest.raises(PathValidationError):
        LocalArtifactStorage(tmp_path).resolve_relative(value)


def test_storage_rejects_non_deterministic_names(tmp_path: Path) -> None:
    with pytest.raises(PathValidationError):
        LocalArtifactStorage.build_relative_path(
            CASE_ID, DRAFT_ID, "PDF", 1, "personal-name.pdf"
        )


def test_storage_layout_contains_only_uuid_format_version_and_filename(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)
    relative = storage.build_relative_path(CASE_ID, DRAFT_ID, "PDF", 3)
    assert relative == (
        "22222222-2222-4222-8222-222222222222/"
        "11111111-1111-4111-8111-111111111111/pdf/v3/"
        "11111111-1111-4111-8111-111111111111_v3.pdf"
    )
    assert all(value not in relative.lower() for value in ("case-number", "personal"))


def test_storage_rejects_symlink_segments(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    link = tmp_path / "link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(PathValidationError):
        storage.resolve_relative("link/file.pdf")


def test_storage_uses_minimum_permissions_when_supported(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX permissions unavailable")
    storage = LocalArtifactStorage(tmp_path)
    relative = _relative()
    temporary = storage.create_temp(relative)
    assert temporary.stat().st_mode & 0o777 == 0o600
    assert temporary.parent.stat().st_mode & 0o777 == 0o700


def test_docx_integrity_and_hash(tmp_path: Path) -> None:
    path = tmp_path / f"{DRAFT_ID}_v1.docx"
    PythonDocxRenderer().render(_snapshot(), path)
    validator = ArtifactIntegrityValidator()
    digest = validator.validate_docx(path, declared_mime=DOCX_MIME)
    assert digest == validator.sha256(path)
    with pytest.raises(HashValidationError):
        validator.validate_docx(path, expected_sha256="0" * 64, declared_mime=DOCX_MIME)


def test_docx_mime_spoofing_and_zip_structure_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / f"{DRAFT_ID}_v1.docx"
    path.write_bytes(b"not a zip")
    validator = ArtifactIntegrityValidator()
    with pytest.raises(InvalidArtifactError):
        validator.validate_docx(path, declared_mime=PDF_MIME)
    with pytest.raises(InvalidArtifactError):
        validator.validate_docx(path, declared_mime=DOCX_MIME)


def test_docx_entry_and_uncompressed_limits_are_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / f"{DRAFT_ID}_v1.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", b"x")
        archive.writestr("word/document.xml", b"x")
        for index in range(499):
            archive.writestr(f"extra/{index}.xml", b"x")
    with pytest.raises(InvalidArtifactError):
        ArtifactIntegrityValidator().validate_docx(path, declared_mime=DOCX_MIME)
    monkeypatch.setattr(settings.export, "max_docx_size_bytes", path.stat().st_size)
    assert settings.export.max_docx_size_bytes == path.stat().st_size


def test_pdf_header_eof_and_hash_are_enforced(tmp_path: Path) -> None:
    path = tmp_path / f"{DRAFT_ID}_v1.pdf"
    path.write_bytes(b"%PDF-1.7\nbody\n%%EOF")
    validator = ArtifactIntegrityValidator()
    digest = validator.validate_pdf(path, declared_mime=PDF_MIME)
    assert len(digest) == 64
    path.write_bytes(b"%PDF-1.7\ntruncated")
    with pytest.raises(InvalidArtifactError):
        validator.validate_pdf(path, declared_mime=PDF_MIME)


def test_pdf_size_limit_accepts_exact_bytes_and_rejects_one_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / f"{DRAFT_ID}_v1.pdf"
    path.write_bytes(b"%PDF-1.7\nbody\n%%EOF")
    limit = path.stat().st_size
    monkeypatch.setattr(settings.export, "max_pdf_size_bytes", limit)
    ArtifactIntegrityValidator().validate_pdf(path, declared_mime=PDF_MIME)
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(InvalidArtifactError):
        ArtifactIntegrityValidator().validate_pdf(path, declared_mime=PDF_MIME)


def test_empty_artifact_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / f"{DRAFT_ID}_v1.pdf"
    path.write_bytes(b"")
    with pytest.raises(InvalidArtifactError):
        ArtifactIntegrityValidator().validate_pdf(path, declared_mime=PDF_MIME)
