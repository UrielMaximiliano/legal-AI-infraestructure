from __future__ import annotations

import pytest
from pydantic import ValidationError

from legal_ai.schemas.rag import (
    RagDraftGenerationRequest,
    RagStructuredDraft,
    rag_schema,
)


def _raw() -> dict[str, object]:
    return {
        "schema_version": 1,
        "title": "Draft",
        "visto": [{"text": "Visto", "citation_ids": ["SRC-001"]}],
        "considerandos": [
            {"text": "Considerando", "citation_ids": ["SRC-001"]}
        ],
        "dispositive_intro": "Por ello",
        "articles": [{"number": 1, "text": "Designar", "citation_ids": []}],
        "closing": "Comunicar",
        "authority": "Autoridad",
        "signature": "Pendiente",
        "sources": [
            {
                "citation_id": "SRC-001",
                "external_id": "DOC-1",
                "title": "Title",
                "publication_date": None,
                "section_type": "VISTO",
            }
        ],
        "warnings": ["NO VINCULANTE - REVISION HUMANA OBLIGATORIA"],
    }


def test_structured_schema_is_closed_and_deterministically_rendered() -> None:
    draft = RagStructuredDraft.model_validate(_raw())
    assert "ARTICULO 1." in draft.render_for_review()
    assert draft.model_json_schema()["additionalProperties"] is False
    assert "schema_version" in draft.model_json_schema()["required"]


def test_provider_schema_is_structural_closed_and_ref_free() -> None:
    schema = rag_schema()

    def assert_closed(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            assert "$ref" not in value
            assert "$defs" not in value
            for child in value.values():
                assert_closed(child)
        elif isinstance(value, list):
            for child in value:
                assert_closed(child)

    assert_closed(schema)
    assert schema["properties"]["schema_version"]["const"] == 1


def test_structured_schema_rejects_unknown_citations_and_warning_free_output() -> None:
    unknown = _raw()
    unknown["visto"] = [{"text": "Visto", "citation_ids": ["SRC-002"]}]
    with pytest.raises(ValidationError, match="RAG_UNKNOWN_CITATION"):
        RagStructuredDraft.model_validate(unknown)
    invalid_warning = _raw()
    invalid_warning["warnings"] = ["Draft"]
    with pytest.raises(ValidationError, match="RAG_HUMAN_REVIEW_WARNING_REQUIRED"):
        RagStructuredDraft.model_validate(invalid_warning)


def test_generation_request_rejects_hostile_variable_keys() -> None:
    with pytest.raises(ValidationError, match="RAG_VARIABLE_INVALID"):
        RagDraftGenerationRequest(
            template_id="00000000-0000-0000-0000-000000000000",
            case_file_id="00000000-0000-0000-0000-000000000000",
            variables={"Authorization": "secret"},
        )
