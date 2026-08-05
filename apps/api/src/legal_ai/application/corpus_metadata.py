"""Application-level metadata extraction and validation."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from legal_ai.schemas.corpus_metadata import CorpusMetadata, CorpusMetadataError


class CorpusMetadataService:
    """Build a strict metadata DTO without inferring required values."""

    def validate(self, payload: Mapping[str, Any]) -> CorpusMetadata:
        values = dict(payload)
        for key in ("document_type", "document_subtype", "jurisdiction", "language"):
            if key in values and isinstance(values[key], str):
                values[key] = self._canonical_value(values[key])
        try:
            return CorpusMetadata.model_validate(values)
        except (ValidationError, TypeError, ValueError) as exc:
            if isinstance(exc, CorpusMetadataError):
                raise
            raise CorpusMetadataError() from None

    @staticmethod
    def _canonical_value(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.strip())
        ascii_value = "".join(
            character
            for character in decomposed
            if not unicodedata.combining(character)
        )
        return re.sub(r"[^a-zA-Z0-9]+", "_", ascii_value.casefold()).strip("_")

    def extract(
        self,
        payload: Mapping[str, Any] | None = None,
        *,
        source_identifier: str | None = None,
        source_name: str | None = None,
        external_id: str | None = None,
    ) -> CorpusMetadata:
        values: dict[str, Any] = dict(payload or {})
        for name, value in {
            "source_identifier": source_identifier,
            "source_name": source_name,
            "external_id": external_id,
        }.items():
            if value is not None:
                values[name] = value
        return self.validate(values)


CorpusMetadataValidator = CorpusMetadataService
