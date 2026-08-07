"""Exact pgvector search adapter (ANN indexes remain outside the MVP)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.domain.corpus import ReviewStatus, validate_embedding
from legal_ai.domain.semantic_search import SearchFilters, SemanticSearchCandidate

from .corpus_models import CorpusChunkModel, CorpusDocumentModel


class ExactVectorSearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        query_vector: Sequence[float],
        *,
        filters: SearchFilters | Mapping[str, str] | None = None,
        document_type: str = "decreto",
        document_subtype: str = "designacion_transitoria",
        jurisdiction: str = "nacion",
        organization: str | None = None,
        limit: int = 10,
        top_k: int | None = None,
        minimum_score: float | None = None,
        reviewed_only: bool = True,
    ) -> Sequence[SemanticSearchCandidate]:
        language: str | None = None
        if isinstance(filters, Mapping):
            try:
                values = dict(filters)
                allowed_keys = {
                    "document_type",
                    "document_subtype",
                    "jurisdiction",
                    "language",
                    "organization",
                    "review_status",
                }
                if not set(values).issubset(allowed_keys):
                    raise ValueError
                filters = SearchFilters(
                    document_type=values.get("document_type"),
                    document_subtype=values.get("document_subtype"),
                    jurisdiction=values.get("jurisdiction"),
                    language=values.get("language"),
                    organization=values.get("organization"),
                    review_status=values.get("review_status"),
                    reviewed_only=reviewed_only,
                )
            except (TypeError, ValueError):
                raise ValueError("INVALID_SEMANTIC_SEARCH_FILTERS") from None
        if filters is not None:
            document_type = filters.document_type or document_type
            document_subtype = filters.document_subtype or document_subtype
            jurisdiction = filters.jurisdiction or jurisdiction
            organization = filters.organization
            language = filters.language
        elif filters is not None:
            language = filters.language
        review_status = (
            filters.review_status
            if filters is not None and filters.review_status is not None
            else ReviewStatus.REVIEWED.value
        )
        if reviewed_only and review_status != ReviewStatus.REVIEWED.value:
            raise ValueError("INVALID_SEMANTIC_SEARCH_FILTERS")
        if top_k is not None:
            limit = top_k
        try:
            vector = list(query_vector)
            validate_embedding(vector)
        except (TypeError, ValueError):
            raise ValueError("EMBEDDING_VECTOR_INVALID") from None
        if limit <= 0 or limit > 50:
            raise ValueError("SEMANTIC_SEARCH_TOP_K_INVALID")
        if minimum_score is not None and (
            not isinstance(minimum_score, (int, float))
            or not math.isfinite(minimum_score)
            or not 0 <= minimum_score <= 1
        ):
            raise ValueError("SEMANTIC_SEARCH_SCORE_INVALID")
        distance = CorpusChunkModel.embedding.cosine_distance(vector)
        score = func.greatest(func.least(1 - distance, 1), 0).label("score")
        statement = (
            select(
                CorpusDocumentModel.id.label("document_id"),
                CorpusChunkModel.id.label("chunk_id"),
                CorpusDocumentModel.external_id,
                CorpusDocumentModel.source_name,
                CorpusDocumentModel.title,
                CorpusDocumentModel.document_type,
                CorpusDocumentModel.document_subtype,
                CorpusDocumentModel.jurisdiction,
                CorpusDocumentModel.language,
                CorpusDocumentModel.organization,
                CorpusDocumentModel.publication_date,
                CorpusDocumentModel.source_url,
                CorpusChunkModel.section_type,
                CorpusChunkModel.article_number,
                CorpusChunkModel.content,
                CorpusChunkModel.section_index,
                CorpusChunkModel.generation,
                CorpusChunkModel.metadata_json,
                score,
            )
            .join(
                CorpusDocumentModel,
                CorpusDocumentModel.id == CorpusChunkModel.document_id,
            )
            .where(
                CorpusChunkModel.state == "ACTIVE",
                CorpusDocumentModel.review_status == review_status,
                CorpusChunkModel.generation == CorpusDocumentModel.active_generation,
                CorpusDocumentModel.document_type == document_type,
                CorpusDocumentModel.document_subtype == document_subtype,
                CorpusDocumentModel.jurisdiction == jurisdiction,
            )
        )
        if organization is not None:
            statement = statement.where(
                CorpusDocumentModel.organization == organization
            )
        if language is not None:
            statement = statement.where(CorpusDocumentModel.language == language)
        if minimum_score is not None:
            statement = statement.where(score >= minimum_score)
        result = await self._session.execute(
            statement.order_by(
                distance,
                CorpusDocumentModel.publication_date.desc().nullslast(),
                CorpusDocumentModel.id,
                CorpusChunkModel.section_index,
                CorpusChunkModel.paragraph_index,
                CorpusChunkModel.id,
            ).limit(limit)
        )
        candidates: list[SemanticSearchCandidate] = []
        for row in result:
            mapping = row._mapping
            excerpt = " ".join(str(mapping["content"]).split())[:500]
            metadata = mapping["metadata_json"]
            public_metadata = (
                {
                    str(key): value
                    for key, value in metadata.items()
                    if str(key) in {"citation", "page", "source_label"}
                }
                if isinstance(metadata, dict)
                else {}
            )
            candidates.append(
                SemanticSearchCandidate(
                    document_id=mapping["document_id"],
                    chunk_id=mapping["chunk_id"],
                    external_id=mapping["external_id"],
                    source_name=mapping["source_name"],
                    title=mapping["title"],
                    document_type=mapping["document_type"],
                    document_subtype=mapping["document_subtype"],
                    jurisdiction=mapping["jurisdiction"],
                    language=mapping["language"],
                    organization=mapping["organization"],
                    section_type=mapping["section_type"],
                    article_number=mapping["article_number"],
                    excerpt=excerpt,
                    chunk_index=mapping["section_index"],
                    similarity_score=float(mapping["score"]),
                    generation=mapping["generation"],
                    publication_date=(
                        mapping["publication_date"].isoformat()
                        if mapping["publication_date"] is not None
                        else None
                    ),
                    source_url=mapping["source_url"],
                    metadata=public_metadata,
                )
            )
        return tuple(candidates)


PgVectorExactSearch = ExactVectorSearchRepository
