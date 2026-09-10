"""Schemas for legacy and configurable template endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TemplateFieldType = Literal[
    "text", "textarea", "date", "number", "currency", "boolean", "select"
]
TemplateRuleType = Literal["validation", "visibility", "derived"]
TemplateConditionOperator = Literal[
    "equals",
    "not_equals",
    "present",
    "not_present",
    "greater_than",
    "less_than",
    "greater_or_equal",
    "less_or_equal",
]


class TemplateFieldOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    label: str


class TemplateField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", min_length=1, max_length=100
    )
    label: str = Field(min_length=1, max_length=200)
    type: TemplateFieldType = "text"
    help: str | None = Field(default=None, max_length=2_000)
    required: bool = False
    default_value: str | int | float | bool | None = None
    options: list[TemplateFieldOption] = Field(default_factory=list)
    order: int | None = Field(default=None, ge=0)
    read_only: bool = False
    derived_from: str | None = None


class TemplateCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=100)
    operator: TemplateConditionOperator
    value: Any = None


class TemplateRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    type: TemplateRuleType
    field: str | None = None
    block_id: str | None = None
    message: str | None = Field(default=None, max_length=2_000)
    conditions: list[TemplateCondition] = Field(default_factory=list)
    match: Literal["all", "any"] = "all"
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    min_value: str | int | float | None = None
    max_value: str | int | float | None = None
    format: Literal["email", "cuit"] | None = None
    derive: Literal["amount_words", "year_from_date"] | None = None
    source_field: str | None = None


class TemplateBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    type: Literal["heading", "paragraph", "list", "separator"]
    content: str = Field(max_length=20_000)
    level: int | None = Field(default=None, ge=1, le=6)


class _TemplateDefinition(BaseModel):
    body_template: str = Field(min_length=1, max_length=500_000)
    fields: list[TemplateField] = Field(default_factory=list)
    rules: list[TemplateRule] = Field(default_factory=list)
    instructions: str | None = Field(default=None, max_length=20_000)
    blocks: list[TemplateBlock] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class CreateTemplateRequest(_TemplateDefinition):
    """Request to create a template."""

    name: str = Field(min_length=1, max_length=200)
    document_type: str = Field(min_length=1, max_length=50)
    organ_emisor: str | None = Field(default=None, max_length=200)
    normativa: str | None = Field(default=None, max_length=20_000)
    description: str | None = Field(default=None, max_length=20_000)
    revision: int | None = Field(default=None, ge=1)


class UpdateTemplateRequest(BaseModel):
    """Request to update a template."""

    body_template: str | None = Field(default=None, max_length=500_000)
    fields: list[TemplateField] | None = None
    rules: list[TemplateRule] | None = None
    instructions: str | None = Field(default=None, max_length=20_000)
    blocks: list[TemplateBlock] | None = None
    variables: list[str] | None = None
    revision: int | None = Field(default=None, ge=1)
    organ_emisor: str | None = Field(default=None, max_length=200)
    normativa: str | None = Field(default=None, max_length=20_000)
    description: str | None = Field(default=None, max_length=20_000)

    model_config = ConfigDict(extra="forbid")


class TemplateVersionRequest(_TemplateDefinition):
    revision: int | None = Field(default=None, ge=1)


class PublishTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int | None = Field(default=None, ge=1)
    confirm_warnings: bool = False


class TemplateResponse(BaseModel):
    """Template response."""

    id: UUID
    name: str
    document_type: str
    version: int
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    body_template: str
    variables: list[str] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime
    author: str | None = None
    template_version_id: UUID | None = None
    status: str = "PUBLISHED"
    revision: int = 1
    fields: list[TemplateField] = Field(default_factory=list)
    rules: list[TemplateRule] = Field(default_factory=list)
    instructions: str | None = None
    blocks: list[TemplateBlock] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class TemplateVersionResponse(BaseModel):
    id: UUID
    template_version_id: UUID
    version: int
    status: str
    revision: int
    body_template: str
    fields: list[TemplateField] = Field(default_factory=list)
    rules: list[TemplateRule] = Field(default_factory=list)
    instructions: str | None = None
    blocks: list[TemplateBlock] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TemplateImportResponse(BaseModel):
    id: UUID
    status: str
    stage: str
    progress: int = Field(ge=0, le=100)
    pages_total: int | None = None
    pages_processed: int = 0
    body_template: str | None = None
    blocks: list[TemplateBlock] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    retryable: bool = False
    template_version: TemplateVersionResponse | None = None


class TemplateAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(min_length=1, max_length=50)
    body_template: str = Field(min_length=1, max_length=500_000)
    fields: list[TemplateField] = Field(default_factory=list)


class TemplateSuggestionOccurrence(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str


class TemplateSuggestion(BaseModel):
    key: str
    label: str
    type: TemplateFieldType = "text"
    fragment: str
    start: int | None = None
    end: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    occurrences: list[TemplateSuggestionOccurrence] = Field(default_factory=list)


class TemplateAnalysisResponse(BaseModel):
    id: UUID
    status: str
    suggestions: list[TemplateSuggestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class TemplatePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    body_template: str = Field(min_length=1, max_length=500_000)
    fields: list[TemplateField] = Field(default_factory=list)
    rules: list[TemplateRule] = Field(default_factory=list)
    blocks: list[TemplateBlock] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)


class TemplatePreviewResponse(BaseModel):
    document: dict[str, Any]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
