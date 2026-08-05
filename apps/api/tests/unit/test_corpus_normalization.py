import pytest

from legal_ai.application.corpus_normalization import (
    CorpusNormalizationError,
    CorpusNormalizationService,
    NormalizationConfig,
)


def test_normalization_hash_and_idempotency() -> None:
    service = CorpusNormalizationService()
    first = service.normalize("\ufeffLey N° 1\r\n\r\nArtículo 1°")
    second = service.normalize(first.normalized_content)
    assert first.normalized_content == second.normalized_content
    assert first.normalized_content_hash == second.normalized_content_hash


def test_normalization_removes_configured_and_web_artifacts() -> None:
    service = CorpusNormalizationService(
        NormalizationConfig(
            version="005-test-v2",
            headers=("Boletín Oficial",),
            footers=("Pie de página",),
        )
    )
    result = service.normalize(
        "Boletín Oficial\n\nVISTO\t el expediente\n\nMenu\n\nPie de página"
    )
    assert result.normalization_version == "005-test-v2"
    assert result.normalized_content == "VISTO el expediente"
    assert result.transformation_report["web_or_configured_lines_removed"] == 3


@pytest.mark.parametrize("value", ["", "   ", None])
def test_normalization_rejects_empty_input(value: object) -> None:
    with pytest.raises(CorpusNormalizationError):
        CorpusNormalizationService().normalize(value)  # type: ignore[arg-type]


def test_normalization_rejects_empty_version_and_all_control_characters() -> None:
    with pytest.raises(CorpusNormalizationError, match="VERSION_INVALID"):
        CorpusNormalizationService().normalize(
            "contenido", config=NormalizationConfig(version=" ")
        )
    with pytest.raises(CorpusNormalizationError, match="NORMALIZED_CONTENT_EMPTY"):
        CorpusNormalizationService().normalize("\x00\x01\x02")
