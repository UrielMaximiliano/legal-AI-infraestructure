from __future__ import annotations

from pathlib import Path

import pytest

from legal_ai.adapters.filesystem_corpus import (
    CorpusReaderError,
    FilesystemCorpusReader,
)
from legal_ai.application.corpus_metadata import CorpusMetadataService
from legal_ai.application.corpus_normalization import CorpusNormalizationService
from legal_ai.application.legal_chunking import LegalChunkingService, SectionType
from legal_ai.cli.corpus import main


@pytest.mark.asyncio
async def test_filesystem_reader_is_stable_and_extracts_visible_text(
    tmp_path: Path,
) -> None:
    (tmp_path / "b.txt").write_text("Ley N° 1", encoding="utf-8")
    (tmp_path / "a.html").write_text(
        "<nav>Menu</nav><p>VISTO</p><script>alert(1)</script><p>Decreto</p>",
        encoding="utf-8",
    )
    reader = FilesystemCorpusReader(tmp_path)
    assert await reader.discover() == ("a.html", "b.txt")
    assert await reader.read("a.html") == "VISTO\n\nDecreto"
    with pytest.raises(CorpusReaderError) as error:
        await reader.read("../secret.txt")
    assert error.value.code == "CORPUS_SOURCE_IDENTIFIER_INVALID"


def test_reader_rejects_invalid_encoding_and_size(tmp_path: Path) -> None:
    (tmp_path / "bad.txt").write_bytes(b"\xff\xfe\x00\x00")
    reader = FilesystemCorpusReader(tmp_path)
    with pytest.raises(CorpusReaderError) as error:
        reader.read_sync("bad.txt")
    assert error.value.code == "CORPUS_ENCODING_INVALID"
    (tmp_path / "large.txt").write_text("12345", encoding="utf-8")
    reader = FilesystemCorpusReader(tmp_path, max_file_size_bytes=2)
    assert reader.discover_sync() == ()
    report = reader.discover_report_sync()
    assert report.failures[0].error_code == "CORPUS_FILE_TOO_LARGE"


def test_normalization_is_versioned_hashed_and_idempotent() -> None:
    service = CorpusNormalizationService()
    first = service.normalize("\ufeffARTICULO 1°\r\n\r\nLey N° 123\x00")
    second = service.normalize(first.normalized_content)
    assert first.normalized_content == "ARTÍCULO 1°\n\nLey N° 123"
    assert first.normalized_content == second.normalized_content
    assert len(first.raw_content_hash) == 64
    assert len(first.normalized_content_hash) == 64
    assert first.transformation_report["controls_removed"] == 1


def test_metadata_requires_mvp_values_and_does_not_echo_invalid_payload() -> None:
    service = CorpusMetadataService()
    metadata = service.extract(
        {
            "external_id": "dec-1",
            "source_name": "boletin",
            "source_identifier": "decretos/dec-1.txt",
            "document_type": "decreto",
            "document_subtype": "designacion_transitoria",
            "jurisdiction": "nacion",
            "language": "es",
        }
    )
    assert metadata.source_identifier == "decretos/dec-1.txt"
    with pytest.raises(ValueError) as error:
        service.extract({"external_id": "x"})
    assert str(error.value) == "CORPUS_METADATA_INVALID"


def test_legal_chunking_preserves_articles_and_is_deterministic() -> None:
    content = (
        "DECRETO N° 1\n\nVISTO el expediente EX-1-2026.\n\n"
        "CONSIDERANDO:\n\nQue corresponde designar.\n\n"
        "ARTÍCULO 1°.- Desígnase a Ana en la Secretaría.\n\n"
        "ARTICULO 2º.- Comuníquese.\n\nPUBLÍQUESE."
    )
    chunker = LegalChunkingService(max_chunk_chars=20)
    first = chunker.chunk(content)
    second = chunker.chunk(content)
    assert [chunk.content for chunk in first] == [chunk.content for chunk in second]
    assert any(chunk.section_type is SectionType.VISTO for chunk in first)
    articles = [chunk for chunk in first if chunk.section_type is SectionType.ARTICLE]
    assert [chunk.article_number for chunk in articles] == ["1", "2"]
    assert "EX-1-2026" in first[1].content
    assert all(chunk.content and len(chunk.content_hash) == 64 for chunk in first)


def test_chunking_fixture_covers_legal_sections_without_cutting_references() -> None:
    fixture = Path("tests/fixtures/corpus/decretos/decreto_designacion.txt").read_text(
        encoding="utf-8"
    )
    chunks = LegalChunkingService(max_chunk_chars=40).chunk(fixture)
    sections = {chunk.section_type for chunk in chunks}
    assert SectionType.HEADER in sections
    assert SectionType.VISTO in sections
    assert SectionType.CONSIDERANDO in sections
    assert SectionType.DISPOSITIVE_INTRO in sections
    assert SectionType.ARTICLE in sections
    assert SectionType.CLOSING in sections
    assert SectionType.AUTHORITY in sections
    assert SectionType.SIGNATURE in sections or SectionType.UNKNOWN in sections
    visto = next(chunk for chunk in chunks if chunk.section_type is SectionType.VISTO)
    assert "EX-2026-00000001-APN-BO#JGM" in visto.content
    assert "Ley N° 25.164" in visto.content


def test_cli_dry_run_has_no_sensitive_paths_or_content(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    (tmp_path / "decreto.txt").write_text(
        "ARTÍCULO 1°.- Designación transitoria.", encoding="utf-8"
    )

    class EmptyLookup:
        async def lookup(self, **kwargs):
            return ()

    monkeypatch.setattr(
        "legal_ai.cli.corpus.SQLAlchemyCorpusDeduplicationLookup",
        lambda session: EmptyLookup(),
    )
    assert main(["ingest", str(tmp_path), "--output", "json"]) == 0
    output = capsys.readouterr().out
    assert "DRY_RUN" in output
    assert str(tmp_path) not in output
    assert "Designación transitoria" not in output
    assert "qwen3-embedding:4b-q4_K_M" in output


def test_cli_rejects_resume_without_execute(tmp_path: Path, capsys) -> None:
    assert main(["ingest", str(tmp_path), "--resume", "--run-id", "r1"]) == 2
    assert "CORPUS_RESUME_REQUIRES_EXECUTE_AND_RUN_ID" in capsys.readouterr().out
