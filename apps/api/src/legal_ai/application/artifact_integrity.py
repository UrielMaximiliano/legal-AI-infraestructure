"""Streaming integrity and format validation for DOCX and PDF artifacts."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path, PurePosixPath

from legal_ai.config import settings
from legal_ai.domain.errors import (
    FilesystemError,
    HashValidationError,
    InvalidArtifactError,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_DOCX_ENTRIES = 500
MAX_COMPRESSION_RATIO = 100


class ArtifactIntegrityValidator:
    """Validate bytes before publication and before a future download."""

    def validate_docx(
        self,
        path: Path,
        expected_sha256: str | None = None,
        declared_mime: str | None = None,
    ) -> str:
        self._validate_extension(path, "docx")
        self._validate_mime(declared_mime, DOCX_MIME)
        self._validate_size(path, settings.export.max_docx_size_bytes)
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_DOCX_ENTRIES:
                    raise InvalidArtifactError()
                names = {info.filename for info in infos}
                if (
                    "[Content_Types].xml" not in names
                    or "word/document.xml" not in names
                ):
                    raise InvalidArtifactError()
                total_uncompressed = 0
                total_compressed = 0
                for info in infos:
                    self._validate_zip_member(info.filename)
                    total_uncompressed += info.file_size
                    total_compressed += info.compress_size
                if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise InvalidArtifactError()
                if total_uncompressed > MAX_COMPRESSION_RATIO * max(
                    total_compressed, 1
                ):
                    raise InvalidArtifactError()
        except InvalidArtifactError:
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
            raise InvalidArtifactError() from exc
        return self._validate_hash(path, expected_sha256)

    def validate_pdf(
        self,
        path: Path,
        expected_sha256: str | None = None,
        declared_mime: str | None = None,
    ) -> str:
        self._validate_extension(path, "pdf")
        self._validate_mime(declared_mime, PDF_MIME)
        self._validate_size(path, settings.export.max_pdf_size_bytes)
        try:
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise InvalidArtifactError()
                handle.seek(
                    max(0, path.stat().st_size - settings.export.pdf_eof_tail_bytes)
                )
                if b"%%EOF" not in handle.read():
                    raise InvalidArtifactError()
        except InvalidArtifactError:
            raise
        except (OSError, ValueError) as exc:
            raise InvalidArtifactError() from exc
        return self._validate_hash(path, expected_sha256)

    @staticmethod
    def sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
        """Hash a file incrementally without buffering the full artifact."""
        if chunk_size <= 0:
            raise InvalidArtifactError()
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(chunk_size):
                    digest.update(chunk)
        except OSError as exc:
            raise FilesystemError() from exc
        return digest.hexdigest()

    @staticmethod
    def _validate_extension(path: Path, extension: str) -> None:
        name = path.name.lower()
        if not name.endswith(f".{extension}") or name.count(".") != 1:
            raise InvalidArtifactError()

    @staticmethod
    def _validate_mime(declared: str | None, expected: str) -> None:
        if declared is not None and declared != expected:
            raise InvalidArtifactError()

    @staticmethod
    def _validate_size(path: Path, limit: int) -> None:
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise FilesystemError() from exc
        if size <= 0 or size > limit:
            raise InvalidArtifactError(
                details={"size_bytes": size, "limit_bytes": limit}
            )

    def _validate_hash(self, path: Path, expected: str | None) -> str:
        digest = self.sha256(path)
        if expected is not None and digest.lower() != expected.lower():
            raise HashValidationError()
        return digest

    @staticmethod
    def _validate_zip_member(name: str) -> None:
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
            raise InvalidArtifactError()
