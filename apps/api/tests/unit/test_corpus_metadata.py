import pytest

from legal_ai.application.corpus_metadata import CorpusMetadataService


def test_mvp_metadata_contract() -> None:
    metadata = CorpusMetadataService().validate(
        {
            "external_id": "fixture-1",
            "source_name": "filesystem",
            "source_identifier": "fixture.txt",
            "document_type": "decreto",
            "document_subtype": "designacion_transitoria",
            "jurisdiction": "nacion",
            "language": "es",
        }
    )
    assert metadata.document_type == "decreto"


def test_metadata_normalizes_contract_values_and_optional_fields() -> None:
    metadata = CorpusMetadataService().validate(
        {
            "external_id": "fixture-2",
            "source_name": "filesystem",
            "source_identifier": r"fixture\\fixture-2.txt",
            "document_type": " Decreto ",
            "document_subtype": "Designación transitoria",
            "jurisdiction": "NACIÓN",
            "language": " ES ",
            "source_url": "https://example.test/decreto",
            "publication_date": "2026-01-02",
            "cited_norms": ["Ley N° 1"],
        }
    )
    assert metadata.document_subtype == "designacion_transitoria"
    assert metadata.source_identifier == "fixture/fixture-2.txt"
    assert metadata.publication_date.isoformat() == "2026-01-02"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"source_identifier": "../escape"},
        {
            "external_id": "x",
            "source_name": "filesystem",
            "source_identifier": r"C:\\secret.txt",
            "document_type": "decreto",
            "document_subtype": "designacion_transitoria",
            "jurisdiction": "nacion",
            "language": "es",
            "source_url": "http://insecure.example",
        },
        {
            "external_id": "x",
            "source_name": "filesystem",
            "source_identifier": "fixture.txt",
            "document_type": "decreto",
            "document_subtype": "designacion_transitoria",
            "jurisdiction": "nacion",
            "language": "es",
            "cited_norms": ["Ley N° 1", "Ley N° 1"],
        },
    ],
)
def test_metadata_rejects_missing_or_unsafe_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="CORPUS_"):
        CorpusMetadataService().validate(payload)
