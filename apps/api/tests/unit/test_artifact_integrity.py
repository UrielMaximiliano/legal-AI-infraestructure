"""Contract-focused DOCX/PDF integrity tests."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from uuid import UUID

import pytest

from legal_ai.application.artifact_integrity import (
    DOCX_MIME,
    PDF_MIME,
    ArtifactIntegrityValidator,
)
from legal_ai.config import settings
from legal_ai.domain.enums import ExportStatus
from legal_ai.domain.errors import HashValidationError, InvalidArtifactError
from tests.integration.factories_004 import (
    approved_draft,
    export_for,
    review_for,
)

DRAFT_ID = UUID("11111111-1111-4111-8111-111111111111")
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
VALID_DOCX = FIXTURE_DIR / "valid_document.docx"


def test_valid_docx_has_required_zip_entries_and_digest(tmp_path: Path) -> None:
    validator = ArtifactIntegrityValidator()
    digest = validator.validate_docx(VALID_DOCX, declared_mime=DOCX_MIME)
    assert len(digest) == 64
    with pytest.raises(HashValidationError):
        validator.validate_docx(VALID_DOCX, "0" * 64, DOCX_MIME)


def test_docx_entry_limit_and_pdf_signatures(tmp_path: Path) -> None:
    docx = tmp_path / f"{DRAFT_ID}_v2.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", b"x")
        archive.writestr("word/document.xml", b"x")
        for index in range(499):
            archive.writestr(f"extra/{index}.xml", b"x")
    with pytest.raises(InvalidArtifactError):
        ArtifactIntegrityValidator().validate_docx(docx, declared_mime=DOCX_MIME)

    pdf = tmp_path / f"{DRAFT_ID}_v1.pdf"
    pdf.write_bytes(b"%PDF-1.7\ncontenido\n%%EOF")
    assert ArtifactIntegrityValidator().validate_pdf(pdf, declared_mime=PDF_MIME)
    pdf.write_bytes(b"%PDF-1.7\ntruncado")
    with pytest.raises(InvalidArtifactError):
        ArtifactIntegrityValidator().validate_pdf(pdf, declared_mime=PDF_MIME)


def test_docx_compression_ratio_and_double_extension_are_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / f"{DRAFT_ID}_v5.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"x")
        archive.writestr("word/document.xml", b"x")
        archive.writestr("repeated.bin", b"a" * 10000)
    with pytest.raises(InvalidArtifactError):
        ArtifactIntegrityValidator().validate_docx(path, declared_mime=DOCX_MIME)

    double_extension = tmp_path / f"{DRAFT_ID}_v1.final.pdf"
    double_extension.write_bytes(b"%PDF-1.7\n%%EOF")
    with pytest.raises(InvalidArtifactError):
        ArtifactIntegrityValidator().validate_pdf(
            double_extension, declared_mime=PDF_MIME
        )


def test_default_limits_are_exact_bytes() -> None:
    assert settings.export.max_docx_size_bytes == 20_971_520
    assert settings.export.max_pdf_size_bytes == 31_457_280


def test_docx_exact_limit_and_one_byte_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / f"{DRAFT_ID}_v3.docx"
    shutil.copyfile(VALID_DOCX, path)
    monkeypatch.setattr(settings.export, "max_docx_size_bytes", path.stat().st_size)
    validator = ArtifactIntegrityValidator()
    validator.validate_docx(path, declared_mime=DOCX_MIME)
    path.write_bytes(path.read_bytes() + b"\0")
    with pytest.raises(InvalidArtifactError):
        validator.validate_docx(path, declared_mime=DOCX_MIME)


def test_corruption_does_not_mutate_generated_status(tmp_path: Path) -> None:
    draft = approved_draft()
    export = export_for(draft, review_for(draft))
    export.status = ExportStatus.GENERATED
    path = tmp_path / f"{DRAFT_ID}_v4.pdf"
    path.write_bytes(b"corrupt")
    with pytest.raises(InvalidArtifactError):
        ArtifactIntegrityValidator().validate_pdf(path, declared_mime=PDF_MIME)
    assert export.status == ExportStatus.GENERATED
