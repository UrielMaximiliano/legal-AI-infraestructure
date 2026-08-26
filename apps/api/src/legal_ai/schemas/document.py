"""Canonical structured document contract shared by manual and AI drafts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from legal_ai.schemas.rag import RagSource

_CITATION_RE = re.compile(r"^SRC-[0-9]{3}$")
_HUMAN_REVIEW_WARNING = "BORRADOR NO VINCULANTE; REVISION HUMANA OBLIGATORIA."


class DraftParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: StrictStr = Field(min_length=1, max_length=20_000)
    citation_ids: list[str] = Field(default_factory=list)

    @field_validator("citation_ids")
    @classmethod
    def validate_citation_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(
            not _CITATION_RE.fullmatch(item) for item in value
        ):
            raise ValueError("DRAFT_CITATION_ID_INVALID")
        return value


class DraftArticle(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    number: StrictInt = Field(ge=1, le=999)
    text: StrictStr = Field(min_length=1, max_length=20_000)
    citation_ids: list[str] = Field(default_factory=list)

    @field_validator("citation_ids")
    @classmethod
    def validate_citation_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(
            not _CITATION_RE.fullmatch(item) for item in value
        ):
            raise ValueError("DRAFT_CITATION_ID_INVALID")
        return value


class DraftDocument(BaseModel):
    """Editable document representation; legacy plaintext remains readable."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: StrictInt = Field(default=1)
    title: StrictStr = Field(min_length=1, max_length=20_000)
    visto: list[DraftParagraph] = Field(default_factory=list)
    considerandos: list[DraftParagraph] = Field(default_factory=list)
    dispositive_intro: str = Field(default="", max_length=20_000)
    articles: list[DraftArticle] = Field(default_factory=list)
    closing: str = Field(default="", max_length=20_000)
    authority: str = Field(default="", max_length=20_000)
    signature: str = Field(default="", max_length=20_000)
    sources: list[RagSource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=lambda: [_HUMAN_REVIEW_WARNING])

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("DRAFT_SCHEMA_VERSION_UNSUPPORTED")
        return value

    @field_validator("warnings")
    @classmethod
    def validate_warnings(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(not item.strip() for item in value):
            raise ValueError("DRAFT_WARNINGS_INVALID")
        if not any("NO VINCULANTE" in item.upper() for item in value):
            raise ValueError("DRAFT_HUMAN_REVIEW_WARNING_REQUIRED")
        return value

    def render(self) -> str:
        """Render the structured document deterministically for old consumers."""

        lines = [self.title]
        if self.visto:
            lines.append("VISTO")
            lines.extend(f"- {item.text}" for item in self.visto)
        if self.considerandos:
            lines.append("CONSIDERANDOS")
            lines.extend(f"- {item.text}" for item in self.considerandos)
        for value in (
            self.dispositive_intro,
            *(f"ARTICULO {item.number}. {item.text}" for item in self.articles),
            self.closing,
            self.authority,
            self.signature,
        ):
            if value:
                lines.append(value)
        lines.append("ADVERTENCIAS")
        lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class LegalDocument(DraftDocument):
    """Editor contract including server-derived type and locale."""

    document_type: str = Field(min_length=1, max_length=50)
    locale: str = Field(default="es-AR", min_length=2, max_length=16)
    institutional_header: str = Field(default="", max_length=2_000)

    def validate_for_approval(self) -> None:
        """Validate the minimum legal shape before a review can be approved."""

        required = {
            "title": self.title,
            "dispositive_intro": self.dispositive_intro,
            "closing": self.closing,
            "authority": self.authority,
            "signature": self.signature,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing or not self.articles:
            raise ValueError("STRUCTURED_DOCUMENT_INCOMPLETE")


class DraftDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    draft_id: UUID
    draft_version: int
    document: LegalDocument
    source: str
    document_hash: str
    updated_at: datetime


class CreateManualDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: UUID
    case_file_id: UUID
    variables: dict[str, str] = Field(default_factory=dict)
    document: LegalDocument


class UpdateDraftDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)
    document: LegalDocument
