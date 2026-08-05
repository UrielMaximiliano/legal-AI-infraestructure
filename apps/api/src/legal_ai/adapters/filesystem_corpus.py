"""Constrained filesystem reader for the 005 corpus.

The adapter deliberately exposes relative source identifiers only.  It never
follows links, performs network access, or includes a local path in a public
error.  Parsing is kept here (the adapter boundary); normalization and
metadata validation remain pure application services.
"""

from __future__ import annotations

import codecs
import json
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any

from legal_ai.ports.corpus_source import sanitize_source_identifier


class CorpusReaderError(ValueError):
    """Sanitized, stable error raised while discovering or reading a source."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CorpusSourceFile:
    """A parsed source file without an absolute path."""

    source_identifier: str
    extension: str
    media_type: str
    text: str = field(repr=False)
    size_bytes: int
    metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class CorpusDiscoveryFailure:
    source_identifier: str
    error_code: str
    stage: str = "DISCOVERY"
    message: str = ""

    def __post_init__(self) -> None:
        if not self.message:
            object.__setattr__(self, "message", self.error_code)


@dataclass(frozen=True, slots=True)
class CorpusDiscoveryResult:
    files: tuple[str, ...]
    failures: tuple[CorpusDiscoveryFailure, ...] = ()


class _VisibleHTMLParser(HTMLParser):
    """Extract visible text without executing HTML or resolving resources."""

    _ignored = frozenset(
        {"script", "style", "noscript", "template", "nav", "footer", "head"}
    )
    _blocks = frozenset(
        {
            "address",
            "article",
            "br",
            "dd",
            "div",
            "dl",
            "dt",
            "h1",
            "h2",
            "h3",
            "h4",
            "li",
            "p",
            "section",
            "tr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.casefold()
        if tag in self._ignored:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag in self._blocks:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self._ignored and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag in self._blocks:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


class FilesystemCorpusReader:
    """Read only regular, supported files below one canonical root."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        max_file_size_bytes: int = 2 * 1024 * 1024,
        max_files: int = 10_000,
        allowed_extensions: tuple[str, ...] = (".txt", ".json", ".html"),
    ) -> None:
        if max_file_size_bytes <= 0 or max_files <= 0:
            raise ValueError("CORPUS_LIMIT_INVALID")
        self.root = Path(root) if root is not None else None
        self._active_root: Path | None = None
        self.max_file_size_bytes = max_file_size_bytes
        self.max_files = max_files
        self.allowed_extensions = tuple(
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in allowed_extensions
        )
        if not self.allowed_extensions:
            raise ValueError("CORPUS_ALLOWED_EXTENSIONS_INVALID")

    def _canonical_root(self, root: str | Path | None = None) -> Path:
        candidate = (
            Path(root)
            if root is not None
            else (self._active_root if self._active_root is not None else self.root)
        )
        if candidate is None or not candidate.exists() or not candidate.is_dir():
            raise CorpusReaderError("CORPUS_PATH_INVALID")
        if candidate.is_symlink():
            raise CorpusReaderError("CORPUS_SYMLINK_NOT_ALLOWED")
        try:
            return candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            raise CorpusReaderError("CORPUS_PATH_INVALID") from None

    @staticmethod
    def _relative_identifier(root: Path, path: Path) -> str:
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            raise CorpusReaderError("CORPUS_SYMLINK_ESCAPE") from None
        identifier = PurePosixPath(relative.as_posix())
        if identifier.is_absolute() or ".." in identifier.parts:
            raise CorpusReaderError("CORPUS_SOURCE_IDENTIFIER_INVALID")
        try:
            return sanitize_source_identifier(identifier.as_posix())
        except ValueError:
            raise CorpusReaderError("CORPUS_SOURCE_IDENTIFIER_INVALID") from None

    def _resolve_identifier(self, source_identifier: str) -> tuple[Path, str]:
        root = self._canonical_root()
        try:
            identifier = sanitize_source_identifier(source_identifier)
            relative = PurePosixPath(identifier)
        except (TypeError, ValueError):
            raise CorpusReaderError("CORPUS_SOURCE_IDENTIFIER_INVALID") from None
        if not identifier or relative.is_absolute() or ".." in relative.parts:
            raise CorpusReaderError("CORPUS_SOURCE_IDENTIFIER_INVALID")
        path = root.joinpath(*relative.parts)
        if path.is_symlink():
            try:
                resolved_link = path.resolve(strict=True)
                resolved_link.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                raise CorpusReaderError("CORPUS_SYMLINK_ESCAPE") from None
            raise CorpusReaderError("CORPUS_SYMLINK_NOT_ALLOWED")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            raise CorpusReaderError("CORPUS_SYMLINK_ESCAPE") from None
        if not resolved.is_file() or resolved.is_symlink():
            raise CorpusReaderError("CORPUS_FILE_INVALID")
        return resolved, identifier

    def _check_extension(self, identifier: str) -> str:
        extension = Path(identifier).suffix.casefold()
        if extension not in self.allowed_extensions:
            raise CorpusReaderError("CORPUS_EXTENSION_NOT_ALLOWED")
        return extension

    def discover_report_sync(
        self, root: str | Path | None = None, *, fail_fast: bool = False
    ) -> CorpusDiscoveryResult:
        canonical = self._canonical_root(root)
        self._active_root = canonical
        identifiers: list[str] = []
        failures: list[CorpusDiscoveryFailure] = []
        try:
            candidates = sorted(
                canonical.rglob("*"),
                key=lambda p: (p.as_posix().casefold(), p.as_posix()),
            )
        except OSError:
            raise CorpusReaderError("CORPUS_DISCOVERY_FAILED") from None
        for path in candidates:
            if path.is_symlink():
                # Links are never accepted.  Keep the error stable and
                # distinguish a link that escapes the root from one that does
                # not, so callers can report the security policy precisely.
                try:
                    resolved_link = path.resolve(strict=True)
                    resolved_link.relative_to(canonical)
                    link_error = "CORPUS_SYMLINK_NOT_ALLOWED"
                except (OSError, RuntimeError, ValueError):
                    link_error = "CORPUS_SYMLINK_ESCAPE"
                failure = CorpusDiscoveryFailure(
                    self._safe_candidate_identifier(canonical, path),
                    link_error,
                )
                failures.append(failure)
                if fail_fast:
                    break
                continue
            if not path.is_file():
                continue
            try:
                identifier = self._relative_identifier(canonical, path)
            except CorpusReaderError as exc:
                failures.append(
                    CorpusDiscoveryFailure(
                        self._safe_candidate_identifier(canonical, path),
                        exc.code,
                    )
                )
                if fail_fast:
                    break
                continue
            if Path(identifier).suffix.casefold() not in self.allowed_extensions:
                failures.append(
                    CorpusDiscoveryFailure(identifier, "CORPUS_EXTENSION_NOT_ALLOWED")
                )
                if fail_fast:
                    break
                continue
            try:
                size = path.stat().st_size
            except OSError:
                failures.append(
                    CorpusDiscoveryFailure(identifier, "CORPUS_FILE_STAT_FAILED")
                )
                if fail_fast:
                    break
                continue
            if size > self.max_file_size_bytes:
                failures.append(
                    CorpusDiscoveryFailure(identifier, "CORPUS_FILE_TOO_LARGE")
                )
                if fail_fast:
                    break
                continue
            identifiers.append(identifier)
            if len(identifiers) > self.max_files:
                raise CorpusReaderError("CORPUS_FILE_COUNT_EXCEEDED")
        return CorpusDiscoveryResult(tuple(identifiers), tuple(failures))

    @staticmethod
    def _safe_candidate_identifier(root: Path, path: Path) -> str:
        try:
            relative = path.absolute().relative_to(root.absolute())
            return sanitize_source_identifier(relative.as_posix())
        except (OSError, ValueError):
            return "<invalid-source>"

    def discover_sync(self, root: str | Path | None = None) -> tuple[str, ...]:
        result = self.discover_report_sync(root)
        # Invalid files are per-file failures, even when every candidate is
        # invalid.  Root/configuration failures still raise from
        # discover_report_sync itself.
        return result.files

    async def discover(self, root: str | Path | None = None) -> tuple[str, ...]:
        return self.discover_sync(root)

    async def discover_report(
        self, root: str | Path | None = None, *, fail_fast: bool = False
    ) -> CorpusDiscoveryResult:
        return self.discover_report_sync(root, fail_fast=fail_fast)

    @staticmethod
    def _decode(raw: bytes) -> str:
        try:
            if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(
                codecs.BOM_UTF16_BE
            ):
                decoded = raw.decode("utf-16")
            elif raw.startswith(codecs.BOM_UTF32_LE) or raw.startswith(
                codecs.BOM_UTF32_BE
            ):
                decoded = raw.decode("utf-32")
            else:
                decoded = raw.decode("utf-8-sig")
            if "\x00" in decoded:
                raise UnicodeDecodeError("utf-8", raw, 0, len(raw), "NUL in text")
            return decoded
        except UnicodeDecodeError:
            raise CorpusReaderError("CORPUS_ENCODING_INVALID") from None

    @staticmethod
    def _parse_json(text: str) -> tuple[str, dict[str, object]]:
        try:
            value: Any = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise CorpusReaderError("CORPUS_PARSE_FAILED") from None
        if not isinstance(value, dict):
            raise CorpusReaderError("CORPUS_JSON_SCHEMA_INVALID")
        allowed = {"content", "text", "metadata", "external_id", "source_identifier"}
        if any(key not in allowed for key in value):
            raise CorpusReaderError("CORPUS_JSON_SCHEMA_INVALID")
        content = value.get("content", value.get("text"))
        if not isinstance(content, str) or not content.strip():
            raise CorpusReaderError("CORPUS_JSON_SCHEMA_INVALID")
        if "metadata" in value and not isinstance(value["metadata"], dict):
            raise CorpusReaderError("CORPUS_JSON_SCHEMA_INVALID")
        metadata = value.get("metadata", {})
        result = dict(metadata) if isinstance(metadata, dict) else {}
        for key in ("external_id", "source_identifier"):
            if key in value:
                identifier = value[key]
                if not isinstance(identifier, str) or not identifier.strip():
                    raise CorpusReaderError("CORPUS_JSON_SCHEMA_INVALID")
                if key == "source_identifier":
                    try:
                        identifier = sanitize_source_identifier(identifier)
                    except ValueError:
                        raise CorpusReaderError(
                            "CORPUS_SOURCE_IDENTIFIER_INVALID"
                        ) from None
                if key in result and result[key] != identifier:
                    raise CorpusReaderError("CORPUS_JSON_SCHEMA_INVALID")
                result[key] = identifier
        return content, result

    @staticmethod
    def _parse_html(text: str) -> str:
        parser = _VisibleHTMLParser()
        try:
            parser.feed(text)
            parser.close()
        except (ValueError, AssertionError):
            raise CorpusReaderError("CORPUS_PARSE_FAILED") from None
        visible = re.sub(r"[ \t]+", " ", parser.text())
        visible = re.sub(r"\n{3,}", "\n\n", visible)
        return visible.strip()

    def read_document_sync(self, source_identifier: str) -> CorpusSourceFile:
        path, identifier = self._resolve_identifier(source_identifier)
        extension = self._check_extension(identifier)
        try:
            before = path.stat()
            flags = os.O_RDONLY
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(str(path), flags | nofollow)
            try:
                opened = os.fstat(fd)
                if path.is_symlink():
                    raise CorpusReaderError("CORPUS_SYMLINK_ESCAPE")
                if (
                    opened.st_size != before.st_size
                    or opened.st_mtime_ns != before.st_mtime_ns
                    or (before.st_ino and opened.st_ino != before.st_ino)
                ):
                    raise CorpusReaderError("CORPUS_FILE_CHANGED_DURING_READ")
                with os.fdopen(fd, "rb") as handle:
                    raw = handle.read(self.max_file_size_bytes + 1)
                fd = -1
            finally:
                if fd >= 0:
                    os.close(fd)
            after = path.stat()
            if (
                after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or (before.st_ino and after.st_ino != before.st_ino)
            ):
                raise CorpusReaderError("CORPUS_FILE_CHANGED_DURING_READ")
        except CorpusReaderError:
            raise
        except OSError:
            raise CorpusReaderError("CORPUS_READ_FAILED") from None
        if len(raw) > self.max_file_size_bytes:
            raise CorpusReaderError("CORPUS_FILE_TOO_LARGE")
        text = self._decode(raw)
        metadata: dict[str, object] | None = None
        if extension == ".json":
            if not re.match(r"^\s*[\[{]", text):
                raise CorpusReaderError("CORPUS_MIME_MISMATCH")
            text, metadata = self._parse_json(text)
            media_type = "application/json"
        elif extension == ".html":
            if not re.search(
                r"<\s*(?:!doctype\s+html|html|head|body|title|h[1-6]|p|article|div|section|script|style|noscript|template|nav|footer)\b",
                text,
                re.I,
            ):
                raise CorpusReaderError("CORPUS_MIME_MISMATCH")
            text = self._parse_html(text)
            media_type = "text/html"
        else:
            media_type = "text/plain; charset=utf-8"
        if not text.strip():
            raise CorpusReaderError("CORPUS_FILE_EMPTY")
        return CorpusSourceFile(
            identifier, extension, media_type, text, len(raw), metadata
        )

    async def read_document(self, source_identifier: str) -> CorpusSourceFile:
        return self.read_document_sync(source_identifier)

    def read_sync(self, source_identifier: str) -> str:
        return self.read_document_sync(source_identifier).text

    async def read(self, source_identifier: str) -> str:
        return self.read_sync(source_identifier)

    # Explicit aliases keep the adapter convenient for synchronous importers
    # without changing the asynchronous port contract.
    discover_files = discover_sync
    read_file = read_sync


# Names used by early callers and by the phase-5 contract.
FilesystemCorpusSource = FilesystemCorpusReader
