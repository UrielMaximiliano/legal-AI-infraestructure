"""Strict, sanitized metadata DTOs for corpus documents."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legal_ai.ports.corpus_source import sanitize_source_identifier


class CorpusMetadataError(ValueError):
    """Stable metadata validation error with no payload echo."""

    code = "CORPUS_METADATA_INVALID"

    def __init__(self, code: str = code) -> None:
        self.code = code
        super().__init__(code)


_SAFE_ID = re.compile(r"^[^\x00-\x1f\x7f]{1,256}$")


def _clean(value: str, maximum: int, code: str = "CORPUS_METADATA_INVALID") -> str:
    if not isinstance(value, str):
        raise CorpusMetadataError(code)
    result = " ".join(value.strip().split())
    if not result or len(result) > maximum:
        raise CorpusMetadataError(code)
    return result


class CorpusMetadata(BaseModel):
    """Contractual fields used by the MVP corpus and persistence mapper."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    external_id: str = Field(min_length=1, max_length=256)
    source_name: str = Field(min_length=1, max_length=255)
    source_identifier: str = Field(min_length=1, max_length=512)
    source_url: str | None = Field(default=None, max_length=2048)
    document_type: Literal["decreto"]
    document_subtype: Literal["designacion_transitoria"]
    jurisdiction: Literal["nacion"]
    language: Literal["es"]
    publication_date: date | None = None
    organization: str | None = Field(default=None, max_length=200)
    authority: str | None = Field(default=None, max_length=200)
    cited_norms: list[str] = Field(default_factory=list, max_length=100)
    provenance_type: Literal["AUTOMATED", "HUMAN_REVIEWED"] = "AUTOMATED"
    normalization_version: str = Field(
        default="005-nfc-v1", min_length=1, max_length=100
    )
    chunking_version: str = Field(default="005-legal-v1", min_length=1, max_length=100)
    pipeline_version: str = Field(default="005", min_length=1, max_length=100)

    @field_validator("external_id")
    @classmethod
    def clean_external_id(cls, value: str) -> str:
        return _clean(value, 256)

    @field_validator("source_name", "organization", "authority")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return None if value is None else _clean(value, 255)

    @field_validator("source_identifier")
    @classmethod
    def clean_identifier(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise CorpusMetadataError("CORPUS_SOURCE_IDENTIFIER_INVALID")
        try:
            return sanitize_source_identifier(value)
        except ValueError:
            raise CorpusMetadataError("CORPUS_SOURCE_IDENTIFIER_INVALID") from None

    @field_validator("source_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _clean(value, 2048)
        if not value.startswith("https://"):
            raise CorpusMetadataError("CORPUS_SOURCE_URL_INVALID")
        return value

    @field_validator("cited_norms")
    @classmethod
    def clean_norms(cls, values: list[str]) -> list[str]:
        if len(values) > 100:
            raise CorpusMetadataError()
        result = [_clean(value, 200) for value in values]
        if len(set(result)) != len(result):
            raise CorpusMetadataError("CORPUS_METADATA_DUPLICATE_NORM")
        return result

    @model_validator(mode="after")
    def validate_contract(self) -> CorpusMetadata:
        if not self.external_id or not self.source_name:
            raise CorpusMetadataError()
        return self

    def sanitized_dict(self) -> dict[str, object]:
        """Return metadata safe to persist or include in a dry-run report."""

        return self.model_dump(mode="json")
