import pytest

from legal_ai.application.legal_chunking import (
    LegalChunkingError,
    LegalChunkingService,
    SectionType,
)


def test_article_variants_are_detected() -> None:
    chunks = LegalChunkingService().chunk("ARTÍCULO 1°.- Uno\n\nARTICULO 2º.- Dos")
    assert [chunk.section_type for chunk in chunks] == [
        SectionType.ARTICLE,
        SectionType.ARTICLE,
    ]


def test_chunking_covers_fallback_signatures_and_versions() -> None:
    service = LegalChunkingService(max_chunk_chars=10)
    chunks = service.chunk_document(
        None,
        "Título\n\nFdo. Autor\n\nPárrafo largo con Ley N° 1 y fecha 2026-01-01",
        normalization_version="norm-v2",
        chunking_version="chunk-v2",
    )
    assert any(chunk.section_type is SectionType.SIGNATURE for chunk in chunks)
    assert all(chunk.chunking_version == "chunk-v2" for chunk in chunks)
    assert all(chunk.normalization_version == "norm-v2" for chunk in chunks)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: LegalChunkingService(chunking_version="", max_chunk_chars=1),
        lambda: LegalChunkingService(max_chunk_chars=0),
    ],
)
def test_chunking_rejects_invalid_configuration(factory) -> None:
    with pytest.raises(LegalChunkingError, match="CONFIG_INVALID"):
        factory()


def test_chunking_rejects_empty_input_and_version() -> None:
    service = LegalChunkingService()
    with pytest.raises(LegalChunkingError, match="NORMALIZED_CONTENT_EMPTY"):
        service.chunk("  ")
    with pytest.raises(LegalChunkingError, match="NORMALIZATION_VERSION_INVALID"):
        service.chunk("texto", normalization_version=" ")
