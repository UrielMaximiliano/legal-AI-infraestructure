from __future__ import annotations

import codecs
import json
import os
from pathlib import Path

import pytest

from legal_ai.adapters import filesystem_corpus
from legal_ai.adapters.filesystem_corpus import (
    CorpusReaderError,
    FilesystemCorpusReader,
)


def test_discovery_returns_relative_supported_identifiers(tmp_path: Path) -> None:
    (tmp_path / "document.txt").write_text("texto", encoding="utf-8")
    (tmp_path / "ignored.pdf").write_bytes(b"pdf")
    assert FilesystemCorpusReader(tmp_path).discover_sync() == ("document.txt",)


def test_reader_rejects_invalid_root_limits_and_identifiers(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="CORPUS_LIMIT_INVALID"):
        FilesystemCorpusReader(tmp_path, max_files=0)
    with pytest.raises(ValueError, match="CORPUS_ALLOWED_EXTENSIONS_INVALID"):
        FilesystemCorpusReader(tmp_path, allowed_extensions=())
    with pytest.raises(CorpusReaderError, match="CORPUS_PATH_INVALID"):
        FilesystemCorpusReader(tmp_path / "missing").discover_sync()
    reader = FilesystemCorpusReader(tmp_path)
    for identifier in (None, "../outside.txt", r"C:\\outside.txt"):
        with pytest.raises(CorpusReaderError):
            reader.read_sync(identifier)  # type: ignore[arg-type]


def test_reader_parses_json_schema_and_rejects_bad_variants(tmp_path: Path) -> None:
    valid = {
        "content": "ARTÍCULO 1°.- Texto",
        "external_id": "json-1",
        "source_identifier": "json/json-1.json",
        "metadata": {"source_name": "fixture"},
    }
    (tmp_path / "valid.json").write_text(json.dumps(valid), encoding="utf-8")
    source = FilesystemCorpusReader(tmp_path).read_document_sync("valid.json")
    assert source.text.startswith("ARTÍCULO")
    assert source.metadata == {
        "source_name": "fixture",
        "external_id": "json-1",
        "source_identifier": "json/json-1.json",
    }
    invalid_payloads = (
        "not-json",
        "[]",
        '{"unknown": "x"}',
        '{"content": ""}',
        '{"content": "x", "metadata": []}',
        '{"content": "x", "source_identifier": "../escape"}',
        '{"content": "x", "external_id": 1}',
        '{"content": "x", "metadata": {"external_id": "one"}, "external_id": "two"}',
    )
    for index, payload in enumerate(invalid_payloads):
        path = tmp_path / f"invalid-{index}.json"
        path.write_text(payload, encoding="utf-8")
        with pytest.raises(CorpusReaderError):
            FilesystemCorpusReader(tmp_path).read_document_sync(path.name)


def test_reader_handles_bom_empty_unsupported_and_count_limits(tmp_path: Path) -> None:
    (tmp_path / "utf16.txt").write_bytes(
        codecs.BOM_UTF16_LE + "texto".encode("utf-16-le")
    )
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    (tmp_path / "unsupported.pdf").write_bytes(b"not a pdf")
    reader = FilesystemCorpusReader(tmp_path, max_files=1)
    with pytest.raises(CorpusReaderError, match="CORPUS_FILE_COUNT_EXCEEDED"):
        reader.discover_sync()
    assert FilesystemCorpusReader(tmp_path).read_sync("utf16.txt") == "texto"
    with pytest.raises(CorpusReaderError, match="CORPUS_FILE_EMPTY"):
        FilesystemCorpusReader(tmp_path).read_document_sync("empty.txt")
    with pytest.raises(CorpusReaderError, match="CORPUS_EXTENSION_NOT_ALLOWED"):
        FilesystemCorpusReader(tmp_path).read_document_sync("unsupported.pdf")


def test_reader_rejects_symlink_escape_when_supported(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-corpus.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "escape.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")
    report = FilesystemCorpusReader(tmp_path).discover_report_sync()
    assert report.files == ()
    assert report.failures[0].error_code == "CORPUS_SYMLINK_ESCAPE"


def test_reader_rejects_in_root_symlink_with_distinct_policy_code(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.txt"
    target.write_text("inside", encoding="utf-8")
    link = tmp_path / "inside-link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")
    report = FilesystemCorpusReader(tmp_path).discover_report_sync()
    assert report.files == ("target.txt",)
    assert [(item.source_identifier, item.error_code) for item in report.failures] == [
        ("inside-link.txt", "CORPUS_SYMLINK_NOT_ALLOWED")
    ]


def test_discovery_isolates_oversized_file_and_preserves_order(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "b.txt").write_text("too large", encoding="utf-8")
    reader = FilesystemCorpusReader(tmp_path, max_file_size_bytes=2)
    result = reader.discover_report_sync()
    assert result.files == ("a.txt",)
    assert [
        (failure.source_identifier, failure.error_code) for failure in result.failures
    ] == [("b.txt", "CORPUS_FILE_TOO_LARGE")]


def test_reader_rejects_extension_mime_mismatch(tmp_path: Path) -> None:
    (tmp_path / "renamed.json").write_text("legal text", encoding="utf-8")
    with pytest.raises(CorpusReaderError, match="CORPUS_MIME_MISMATCH"):
        FilesystemCorpusReader(tmp_path).read_document_sync("renamed.json")


def test_reader_containment_check_is_portable_without_symlink_privileges(
    tmp_path: Path,
) -> None:
    reader = FilesystemCorpusReader(tmp_path)
    with pytest.raises(CorpusReaderError, match="CORPUS_SYMLINK_ESCAPE"):
        reader._relative_identifier(tmp_path, tmp_path.parent / "outside.txt")


def test_reader_rejects_mutation_between_stat_and_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "changed.txt"
    path.write_text("contenido", encoding="utf-8")
    original_fstat = filesystem_corpus.os.fstat

    def changed_fstat(fd: int) -> os.stat_result:
        value = original_fstat(fd)
        values = list(value)
        values[6] = value.st_size + 1
        return os.stat_result(values)

    monkeypatch.setattr(filesystem_corpus.os, "fstat", changed_fstat)
    with pytest.raises(CorpusReaderError, match="CORPUS_FILE_CHANGED_DURING_READ"):
        FilesystemCorpusReader(tmp_path).read_sync("changed.txt")
