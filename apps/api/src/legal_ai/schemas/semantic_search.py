"""Public allowlisted DTOs for semantic retrieval."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


class SemanticSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    document_type: str = Field(min_length=1, max_length=50)
    document_subtype: str = Field(min_length=1, max_length=100)
    jurisdiction: str = Field(min_length=1, max_length=120)
    language: str | None = Field(default=None, max_length=16)
    organization: str | None = Field(default=None, max_length=200)
    review_status: str | None = Field(default=None, max_length=20)
    top_k: int = Field(default=10, gt=0, le=50)
    minimum_score: float | None = Field(default=None, ge=0, le=1)
    filters: dict[str, object] | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def flatten_filter_envelope(cls, values: object) -> object:
        if not isinstance(values, Mapping):
            return values
        payload = dict(values)
        nested = payload.pop("filters", None)
        if nested is None:
            return payload
        if not isinstance(nested, Mapping):
            raise ValueError("INVALID_SEMANTIC_SEARCH_FILTERS")
        for key, value in nested.items():
            if key in payload and payload[key] != value:
                raise ValueError("INVALID_SEMANTIC_SEARCH_FILTERS")
            payload[key] = value
        return payload


class SemanticSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    chunk_id: str
    external_id: str
    source_name: str
    title: str | None = None
    document_type: str
    document_subtype: str
    jurisdiction: str
    language: str
    organization: str | None
    section_type: str
    article_number: str | None
    excerpt: str = Field(max_length=500)
    chunk_index: int
    similarity_score: float
    generation: int
    publication_date: str | None = None
    source_url: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    embedding_model: str = EMBEDDING_MODEL
    embedding_dimensions: int = EMBEDDING_DIMENSIONS


class SemanticSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    result_count: int = Field(ge=0)
    results: tuple[SemanticSearchResult, ...]
