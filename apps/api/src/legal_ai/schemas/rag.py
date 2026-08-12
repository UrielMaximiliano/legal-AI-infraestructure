"""Strict HTTP and structured-output schemas for RAG."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

_CITATION_RE = re.compile(r"^SRC-[0-9]{3}$")
_VARIABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class RagRetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_k: int = Field(default=8, ge=3, le=20)
    minimum_score: float = Field(default=0.0, ge=0.0, le=1.0)
    organization: str | None = Field(default=None, max_length=200)
    language: str = Field(default="es", min_length=2, max_length=16)


class RagDraftGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: UUID
    case_file_id: UUID
    variables: dict[str, str] = Field(default_factory=dict)
    retrieval: RagRetrievalRequest = Field(default_factory=RagRetrievalRequest)

    @field_validator("variables")
    @classmethod
    def validate_variables(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 64:
            raise ValueError("RAG_VARIABLES_TOO_MANY")
        for key, item in value.items():
            if not _VARIABLE_RE.fullmatch(key) or not 0 < len(item.strip()) <= 500:
                raise ValueError("RAG_VARIABLE_INVALID")
        return {key: item.strip() for key, item in value.items()}


class RagCitedParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: StrictStr = Field(min_length=1, max_length=20_000)
    citation_ids: list[str] = Field(min_length=1)

    @field_validator("citation_ids")
    @classmethod
    def validate_citations(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(
            not _CITATION_RE.fullmatch(item) for item in value
        ):
            raise ValueError("RAG_CITATION_ID_INVALID")
        return value


class RagArticle(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    number: StrictInt = Field(ge=1, le=999)
    text: StrictStr = Field(min_length=1, max_length=20_000)
    citation_ids: list[str]

    @field_validator("citation_ids")
    @classmethod
    def validate_citations(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(
            not _CITATION_RE.fullmatch(item) for item in value
        ):
            raise ValueError("RAG_CITATION_ID_INVALID")
        return value


class RagSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    citation_id: str
    external_id: StrictStr = Field(min_length=1, max_length=255)
    title: StrictStr = Field(min_length=1, max_length=500)
    publication_date: date | None
    section_type: StrictStr = Field(min_length=1, max_length=40)
    source_url: AnyUrl | None = Field(
        default=None, json_schema_extra={"maxLength": 2048}
    )

    @field_validator("citation_id")
    @classmethod
    def validate_citation_id(cls, value: str) -> str:
        if not _CITATION_RE.fullmatch(value):
            raise ValueError("RAG_CITATION_ID_INVALID")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url_length(cls, value: AnyUrl | None) -> AnyUrl | None:
        if value is not None and len(str(value)) > 2048:
            raise ValueError("RAG_SOURCE_URL_TOO_LONG")
        return value


class RagStructuredDraft(BaseModel):
    """Version 1 structured decree draft returned by the model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: StrictInt = Field(json_schema_extra={"const": 1})
    title: StrictStr = Field(min_length=1, max_length=20_000)
    visto: list[RagCitedParagraph] = Field(min_length=1)
    considerandos: list[RagCitedParagraph] = Field(min_length=1)
    dispositive_intro: StrictStr = Field(min_length=1, max_length=20_000)
    articles: list[RagArticle] = Field(min_length=1)
    closing: StrictStr = Field(min_length=1, max_length=20_000)
    authority: StrictStr = Field(min_length=1, max_length=20_000)
    signature: StrictStr = Field(min_length=1, max_length=20_000)
    sources: list[RagSource] = Field(min_length=1)
    warnings: list[StrictStr] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("RAG_SCHEMA_VERSION_UNSUPPORTED")
        return value

    @field_validator("warnings")
    @classmethod
    def validate_warnings(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(not item.strip() for item in value):
            raise ValueError("RAG_WARNINGS_INVALID")
        if not any(
            "NO VINCULANTE" in item.upper() and "REVIS" in item.upper()
            for item in value
        ):
            raise ValueError("RAG_HUMAN_REVIEW_WARNING_REQUIRED")
        return value

    @model_validator(mode="after")
    def validate_source_identity(self) -> RagStructuredDraft:
        source_ids = [source.citation_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("RAG_DUPLICATE_CITATION_SOURCE")
        used: list[str] = []
        for paragraph in (*self.visto, *self.considerandos):
            used.extend(paragraph.citation_ids)
        for article in self.articles:
            used.extend(article.citation_ids)
        if not set(used).issubset(set(source_ids)):
            raise ValueError("RAG_UNKNOWN_CITATION")
        if not set(used):
            raise ValueError("RAG_CITATION_COVERAGE_REQUIRED")
        return self

    @property
    def citation_ids(self) -> tuple[str, ...]:
        return tuple(source.citation_id for source in self.sources)

    def render_for_review(self) -> str:
        """Deterministically render the structured draft for the legacy Draft."""

        lines = [self.title, "VISTO"]
        lines.extend(f"- {paragraph.text}" for paragraph in self.visto)
        lines.append("CONSIDERANDOS")
        lines.extend(f"- {paragraph.text}" for paragraph in self.considerandos)
        lines.append(self.dispositive_intro)
        lines.extend(
            f"ARTICULO {article.number}. {article.text}" for article in self.articles
        )
        lines.extend([self.closing, self.authority, self.signature])
        lines.append("ADVERTENCIAS")
        lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines)


class RagDraftSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    template_id: UUID
    case_file_id: UUID
    title: str
    content: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class RagRetrievalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    embedding_model: str = EMBEDDING_MODEL
    embedding_dimensions: int = EMBEDDING_DIMENSIONS


class RagGenerationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    prompt_version: str
    schema_version: int


class RagDraftGenerationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    rag_run_id: UUID
    draft: RagDraftSummary
    structured_draft: RagStructuredDraft
    retrieval: RagRetrievalSummary
    generation: RagGenerationSummary


class RagRunSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str
    document_id: UUID
    chunk_id: UUID
    rank: int
    score: float
    disposition: str


class RagRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    draft_id: UUID | None
    case_file_id: UUID
    template_id: UUID
    status: str
    models: dict[str, Any]
    versions: dict[str, Any]
    retrieval: dict[str, int]
    durations_ms: dict[str, int | None]
    sources: list[RagRunSourceResponse]
    error_code: str | None
    request_id: str
    created_at: datetime
    finished_at: datetime | None


def rag_schema() -> dict[str, Any]:
    """Return the closed, provider-safe generation grammar.

    Ollama-compatible grammar compilers do not consistently support Pydantic's
    ``$defs``, URI/date formats, or every JSON Schema string constraint.  Keep
    the provider schema structural and closed; ``RagStructuredDraft`` remains
    the authoritative validator for all semantic and bounded constraints before
    anything is persisted.
    """

    text = {"type": "string", "minLength": 1}
    citation_id = {
        "type": "string",
        "pattern": "^SRC-[0-9][0-9][0-9]$",
    }

    def array(items: dict[str, Any], *, required: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {"type": "array", "items": items}
        if required:
            value["minItems"] = 1
        return value

    def closed(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": properties,
        }

    cited_paragraph = closed(
        {
            "text": text,
            "citation_ids": array(citation_id, required=True),
        }
    )
    article = closed(
        {
            "number": {"type": "integer", "minimum": 1, "maximum": 999},
            "text": text,
            "citation_ids": array(citation_id),
        }
    )
    source = closed(
        {
            "citation_id": citation_id,
            "external_id": text,
            "title": text,
            "publication_date": {"type": ["string", "null"]},
            "section_type": text,
            "source_url": {"type": ["string", "null"]},
        }
    )
    return closed(
        {
            "schema_version": {"type": "integer", "const": 1},
            "title": text,
            "visto": array(cited_paragraph, required=True),
            "considerandos": array(cited_paragraph, required=True),
            "dispositive_intro": text,
            "articles": array(article, required=True),
            "closing": text,
            "authority": text,
            "signature": text,
            "sources": array(source, required=True),
            "warnings": array(
                {
                    "type": "string",
                    "enum": [
                        "BORRADOR NO VINCULANTE; REVISION HUMANA OBLIGATORIA."
                    ],
                },
                required=True,
            ),
        }
    )


def rag_generation_schema() -> dict[str, Any]:
    """Return only the fields that Ollama must generate.

    ``sources`` and ``warnings`` are authoritative server-owned fields.  They
    are injected after generation from the selected retrieval sources and the
    mandatory review warning, so asking the model to reproduce them wastes the
    bounded context/output window and can truncate otherwise valid JSON.
    """

    schema = rag_schema()
    properties = dict(schema["properties"])
    properties.pop("sources")
    properties.pop("warnings")
    schema["properties"] = properties
    schema["required"] = [
        field for field in schema["required"] if field in properties
    ]
    return schema
