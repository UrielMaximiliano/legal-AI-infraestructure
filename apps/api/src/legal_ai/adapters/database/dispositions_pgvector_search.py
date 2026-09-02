"""pgvector search adapter for the isolated IMI 0.6B legal index."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.domain.semantic_search import SemanticSearchCandidate


class DispositionsVectorSearchRepository:
    """Read only eligible reviewed legal chunks from the isolated index.

    The SQL is deliberately independent from the legacy ORM models.  This
    prevents a 1024-dimensional vector from ever being sent to the legacy
    2560-dimensional mapping.
    """

    def __init__(self, session: AsyncSession, *, embedding_dimensions: int = 1024):
        if embedding_dimensions != 1024:
            raise ValueError("IMI_RAG_EMBEDDING_DIMENSIONS_INVALID")
        self._session = session
        self.embedding_dimensions = embedding_dimensions

    async def search(
        self,
        query_vector: Sequence[float],
        *,
        filters: Mapping[str, str] | None = None,
        top_k: int = 24,
        minimum_score: float = 0.0,
        reviewed_only: bool = True,
        evaluation_split: str = "INDEX_90",
        **_: object,
    ) -> Sequence[SemanticSearchCandidate]:
        vector = list(query_vector)
        if len(vector) != self.embedding_dimensions or not all(
            isinstance(item, (int, float)) and math.isfinite(item) for item in vector
        ):
            raise ValueError("EMBEDDING_VECTOR_INVALID")
        if not 1 <= top_k <= 50 or not 0 <= minimum_score <= 1:
            raise ValueError("RAG_RETRIEVAL_LIMIT_INVALID")
        if evaluation_split != "INDEX_90" or not reviewed_only:
            raise ValueError("RAG_CORPUS_POLICY_INVALID")
        requested = dict(filters or {})
        statement = text(
            """
            SELECT
              d.id AS document_id,
              d.external_id,
              COALESCE(d.title, d.external_id) AS title,
              sc.name AS source_name,
              dt.code AS document_type,
              COALESCE(dst.code, 'general') AS document_subtype,
              j.code AS jurisdiction,
              l.code AS language,
              org.code AS organization,
              d.publication_date,
              d.source_url,
              c.id AS chunk_id,
              c.section_type,
              c.article_number,
              c.content,
              c.section_index,
              c.generation,
              c.content_sha256,
              GREATEST(
                LEAST(1 - (c.embedding <=> CAST(:embedding AS halfvec)), 1),
                0
              ) AS score
            FROM rag.corpus_documents AS d
            JOIN rag.document_types AS dt ON dt.id = d.document_type_id
            LEFT JOIN rag.document_subtypes AS dst
              ON dst.id = d.document_subtype_id
            JOIN rag.jurisdictions AS j ON j.id = d.jurisdiction_id
            LEFT JOIN rag.organizations AS org ON org.id = d.organization_id
            JOIN rag.languages AS l ON l.code = d.language_code
            JOIN rag.source_catalog AS sc ON sc.id = d.source_id
            JOIN rag.corpus_document_versions AS v ON v.document_id = d.id
            JOIN rag.corpus_chunks AS c ON c.document_version_id = v.id
            WHERE d.active
              AND v.is_active
              AND v.review_status_code = 'REVIEWED'
              AND c.state_code = 'ACTIVE'
              AND c.embedding IS NOT NULL
              AND EXISTS (
                SELECT 1
                FROM rag.corpus_document_version_splits AS split
                WHERE split.document_version_id = v.id
                  AND split.split_code = :evaluation_split
              )
              AND (
                CAST(:document_type AS varchar) IS NULL
                OR upper(dt.code) = upper(CAST(:document_type AS varchar))
              )
              AND (
                CAST(:document_subtype AS varchar) IS NULL
                OR upper(COALESCE(dst.code, 'general')) = upper(
                  CAST(:document_subtype AS varchar)
                )
              )
              AND (
                CAST(:jurisdiction AS varchar) IS NULL
                OR upper(j.code) = upper(CAST(:jurisdiction AS varchar))
              )
              AND (
                CAST(:organization AS varchar) IS NULL
                OR upper(org.code) = upper(CAST(:organization AS varchar))
              )
              AND (
                CAST(:language AS varchar) IS NULL
                OR lower(l.code) = lower(CAST(:language AS varchar))
              )
              AND GREATEST(
                LEAST(1 - (c.embedding <=> CAST(:embedding AS halfvec)), 1),
                0
              ) >= :minimum_score
            ORDER BY c.embedding <=> CAST(:embedding AS halfvec),
                     d.publication_date DESC NULLS LAST,
                     d.id,
                     c.section_index,
                     c.paragraph_index,
                     c.id
            LIMIT :top_k
            """
        )
        params = {
            "embedding": json.dumps(vector, separators=(",", ":")),
            "evaluation_split": evaluation_split,
            "document_type": requested.get("document_type"),
            "document_subtype": requested.get("document_subtype"),
            "jurisdiction": requested.get("jurisdiction"),
            "organization": requested.get("organization"),
            "language": requested.get("language"),
            "minimum_score": minimum_score,
            "top_k": top_k,
        }
        result = await self._session.execute(statement, params)
        candidates: list[SemanticSearchCandidate] = []
        for row in result:
            mapping = row._mapping
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
                    excerpt=" ".join(str(mapping["content"]).split())[:500],
                    chunk_index=mapping["section_index"],
                    similarity_score=float(mapping["score"]),
                    generation=mapping["generation"],
                    publication_date=(
                        mapping["publication_date"].isoformat()
                        if mapping["publication_date"] is not None
                        else None
                    ),
                    source_url=mapping["source_url"],
                    content_hash=mapping["content_sha256"],
                )
            )
        return tuple(candidates)
