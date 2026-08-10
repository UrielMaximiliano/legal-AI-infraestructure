"""Deterministic structured provider for tests and local dry-runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from legal_ai.ports.structured_generation import StructuredGenerationError
from legal_ai.schemas.rag import RagStructuredDraft


class FakeStructuredGenerationProvider:
    """Build a valid draft from only supplied citation metadata."""

    model = "qwen3.6:35b"

    def __init__(self, *, invalid_attempts: int = 0) -> None:
        self._invalid_attempts = invalid_attempts
        self.calls = 0

    async def generate_structured(
        self,
        *,
        system_message: str,
        user_message: str,
        schema: Mapping[str, Any],
        temperature: float = 0.1,
        context: Sequence[Mapping[str, Any]] = (),
    ) -> Mapping[str, Any]:
        del system_message, user_message, schema, temperature
        self.calls += 1
        if self.calls <= self._invalid_attempts:
            return {"schema_version": 1, "title": "invalid"}
        evidence = list(context)
        if not evidence:
            raise StructuredGenerationError("RAG_INSUFFICIENT_EVIDENCE")
        sources = [
            {
                "citation_id": str(item["citation_id"]),
                "external_id": str(item.get("external_id", "fake-source")),
                "title": str(item.get("title", "Reviewed antecedent")),
                "publication_date": item.get("publication_date"),
                "section_type": str(item.get("section_type", "CONSIDERANDO")),
                **(
                    {"source_url": item["source_url"]}
                    if item.get("source_url") is not None
                    else {}
                ),
            }
            for item in evidence
        ]
        citation = str(sources[0]["citation_id"])
        draft = RagStructuredDraft.model_validate(
            {
                "schema_version": 1,
                "title": "Assisted draft - Decree",
                "visto": [
                    {
                        "text": "VISTO the case file and reviewed antecedents.",
                        "citation_ids": [citation],
                    }
                ],
                "considerandos": [
                    {
                        "text": "The reviewed antecedents support this draft.",
                        "citation_ids": [citation],
                    }
                ],
                "dispositive_intro": "Therefore, subject to human review,",
                "articles": [
                    {
                        "number": 1,
                        "text": (
                            "Make the temporary designation described in the case file."
                        ),
                        "citation_ids": [citation],
                    }
                ],
                "closing": "Communicate and archive after human review.",
                "authority": "Competent authority pending review",
                "signature": "SIGNATURE PENDING",
                "sources": sources,
                "warnings": [
                    "NO VINCULANTE - REVISION HUMANA OBLIGATORIA",
                ],
            }
        )
        return draft.model_dump(mode="json")

    async def health_check(self) -> Mapping[str, Any]:
        return {"status": "ready", "model": self.model}
