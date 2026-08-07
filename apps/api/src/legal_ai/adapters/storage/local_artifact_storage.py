"""Secure local filesystem implementation for persisted export artifacts."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final
from uuid import UUID

from legal_ai.config import settings
from legal_ai.domain.errors import FilesystemError, PathValidationError

_UUID_RE: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_FILE_RE: Final = re.compile(
    r"^(?P<draft>[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})_v(?P<version>[1-9][0-9]*)\.(?P<ext>docx|pdf)$"
)
_FORMATS: Final = {"DOCX": "docx", "PDF": "pdf"}


class LocalArtifactStorage:
    """Keep all persisted paths relative to one canonical, non-symlink root."""

    def __init__(self, root: Path | str | None = None) -> None:
        configured = Path(root or settings.export.storage_root)
        if configured.exists() and configured.is_symlink():
            raise PathValidationError()
        self._root = configured.resolve(strict=False)

    @property
    def root(self) -> Path:
        """Expose the configured root only to internal callers and tests."""
        return self._root

    @staticmethod
    def build_relative_path(
        case_file_id: UUID | str,
        draft_id: UUID | str,
        artifact_format: str,
        export_version: int,
        file_name: str | None = None,
    ) -> str:
        case_id = LocalArtifactStorage._uuid_text(case_file_id)
        draft = LocalArtifactStorage._uuid_text(draft_id)
        extension = _FORMATS.get(str(artifact_format).upper())
        if extension is None or export_version <= 0:
            raise PathValidationError()
        expected_name = f"{draft}_v{export_version}.{extension}"
        if file_name is not None and file_name != expected_name:
            raise PathValidationError()
        relative = f"{case_id}/{draft}/{extension}/v{export_version}/{expected_name}"
        if (
            len(expected_name) > settings.export.max_file_name_length
            or len(relative) > settings.export.max_relative_path_length
        ):
            raise PathValidationError()
        return relative

    def resolve_relative(self, relative_path: str) -> Path:
        """Validate a persisted relative path and return its safe absolute path."""
        if not isinstance(relative_path, str) or not relative_path:
            raise PathValidationError()
        if len(relative_path) > settings.export.max_relative_path_length:
            raise PathValidationError()
        if "\\" in relative_path:
            raise PathValidationError()
        posix = PurePosixPath(relative_path)
        windows = PureWindowsPath(relative_path)
        if posix.is_absolute() or windows.is_absolute() or windows.drive:
            raise PathValidationError()
        if any(part in {"..", ""} for part in posix.parts):
            raise PathValidationError()
        parts = posix.parts
        if (
            len(parts) != 5
            or not _UUID_RE.fullmatch(parts[0])
            or not _UUID_RE.fullmatch(parts[1])
            or parts[2] not in _FORMATS.values()
            or not parts[3].startswith("v")
            or not parts[3][1:].isdigit()
        ):
            raise PathValidationError()
        file_match = _FILE_RE.fullmatch(parts[4])
        if (
            file_match is None
            or file_match.group("draft") != parts[1]
            or file_match.group("version") != parts[3][1:]
            or file_match.group("ext") != parts[2]
        ):
            raise PathValidationError()
        target = self._root.joinpath(*posix.parts)
        self._assert_no_symlinks(target)
        try:
            target.resolve(strict=False).relative_to(self._root)
        except ValueError as exc:
            raise PathValidationError() from exc
        return target

    def create_temp(self, relative_path: str) -> Path:
        """Create a random temporary file beside its final destination."""
        destination = self.resolve_relative(relative_path)
        try:
            self._mkdir_secure(destination.parent)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix="tmp-",
                suffix=destination.suffix,
                dir=destination.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            self._chmod_file(temporary)
            return temporary
        except (OSError, ValueError) as exc:
            raise FilesystemError() from exc

    def atomic_replace(self, temporary: Path, relative_path: str) -> None:
        """Publish a same-directory temporary using an atomic replace."""
        destination = self.resolve_relative(relative_path)
        temporary = Path(temporary)
        if not temporary.is_absolute():
            raise PathValidationError()
        if temporary.parent != destination.parent:
            raise PathValidationError()
        if temporary.is_symlink() or not temporary.is_file():
            raise PathValidationError()
        try:
            os.replace(temporary, destination)
            self._chmod_file(destination)
        except OSError as exc:
            raise FilesystemError() from exc

    def stream(
        self, relative_path: str, chunk_size: int = 1024 * 1024
    ) -> Iterator[bytes]:
        """Yield an artifact without loading it entirely into memory."""
        if chunk_size <= 0:
            raise PathValidationError()
        path = self.resolve_relative(relative_path)
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(chunk_size):
                    yield chunk
        except OSError as exc:
            raise FilesystemError() from exc

    def exists(self, relative_path: str) -> bool:
        path = self.resolve_relative(relative_path)
        return path.is_file() and not path.is_symlink()

    def delete(self, relative_path: str) -> None:
        """Delete only a regular artifact within the configured root."""
        path = self.resolve_relative(relative_path)
        if path.is_symlink():
            raise PathValidationError()
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            raise FilesystemError() from exc

    def scan_files(self) -> list[tuple[str, int, float]]:
        """List safe regular files as relative paths for manual reconciliation."""
        result: list[tuple[str, int, float]] = []
        if not self._root.exists():
            return result
        for current, directories, files in os.walk(self._root, followlinks=False):
            current_path = Path(current)
            directories[:] = [
                name for name in directories if not (current_path / name).is_symlink()
            ]
            for name in files:
                path = current_path / name
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    relative = path.relative_to(self._root).as_posix()
                    self._assert_no_symlinks(path)
                    path.resolve(strict=False).relative_to(self._root)
                    stat = path.stat()
                except (OSError, ValueError, PathValidationError):
                    continue
                result.append((relative, stat.st_size, stat.st_mtime))
        return result

    def delete_scanned(self, relative_path: str) -> None:
        """Delete a scanned temporary/orphan after repeating root safety checks."""
        if not isinstance(relative_path, str) or not relative_path:
            raise PathValidationError()
        if "\\" in relative_path:
            raise PathValidationError()
        parts = PurePosixPath(relative_path).parts
        if PurePosixPath(relative_path).is_absolute() or any(
            part in {"", ".."} for part in parts
        ):
            raise PathValidationError()
        candidate = self._root.joinpath(*parts)
        self._assert_no_symlinks(candidate)
        try:
            candidate.resolve(strict=False).relative_to(self._root)
            if candidate.exists() and not candidate.is_file():
                raise PathValidationError()
            if candidate.exists():
                candidate.unlink()
        except ValueError as exc:
            raise PathValidationError() from exc
        except OSError as exc:
            raise FilesystemError() from exc

    def health(self) -> bool:
        """Ensure the root is available without returning its internal path."""
        try:
            self._mkdir_secure(self._root)
            return self._root.is_dir() and not self._root.is_symlink()
        except OSError:
            return False

    @staticmethod
    def _uuid_text(value: UUID | str) -> str:
        try:
            text = str(UUID(str(value)))
        except (ValueError, AttributeError) as exc:
            raise PathValidationError() from exc
        if not _UUID_RE.fullmatch(text):
            raise PathValidationError()
        return text

    def _assert_no_symlinks(self, target: Path) -> None:
        relative = target.relative_to(self._root)
        current = self._root
        if current.exists() and current.is_symlink():
            raise PathValidationError()
        for part in relative.parts:
            current /= part
            if current.exists() and current.is_symlink():
                raise PathValidationError()

    @staticmethod
    def _mkdir_secure(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        with suppress(OSError, NotImplementedError):
            path.chmod(0o700)

    @staticmethod
    def _chmod_file(path: Path) -> None:
        with suppress(OSError, NotImplementedError):
            path.chmod(0o600)
