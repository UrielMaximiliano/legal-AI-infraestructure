from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from legal_ai.adapters.database.corpus_models import (
    CorpusChunkModel,
    CorpusDocumentModel,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.pgvector_search import ExactVectorSearchRepository
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.semantic_search import SearchFilters
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS
from tests.integration.test_005_migrations import _chunk_values, _document_values


def test_exact_search_adapter_is_the_mvp_baseline() -> None:
    assert ExactVectorSearchRepository.__name__ == "ExactVectorSearchRepository"


@pytest.mark.asyncio
async def test_exact_search_rejects_invalid_vector_filters_and_thresholds() -> None:
    repository = ExactVectorSearchRepository(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="EMBEDDING_VECTOR_INVALID"):
        await repository.search([0.0] * 3)
    with pytest.raises(ValueError, match="EMBEDDING_VECTOR_INVALID"):
        await repository.search([float("nan")] * EMBEDDING_DIMENSIONS)
    with pytest.raises(ValueError, match="SEMANTIC_SEARCH_TOP_K_INVALID"):
        await repository.search([0.0] * EMBEDDING_DIMENSIONS, limit=0)
    with pytest.raises(ValueError, match="SEMANTIC_SEARCH_SCORE_INVALID"):
        await repository.search([0.0] * EMBEDDING_DIMENSIONS, minimum_score=2)
    with pytest.raises(ValueError, match="INVALID_SEMANTIC_SEARCH_FILTERS"):
        await repository.search(
            [0.0] * EMBEDDING_DIMENSIONS, filters={"token": "secret"}
        )
    pending = SearchFilters(
        document_type="decreto",
        document_subtype="designacion_transitoria",
        jurisdiction="nacion",
        review_status="PENDING_REVIEW",
        reviewed_only=False,
    )
    with pytest.raises(ValueError, match="INVALID_SEMANTIC_SEARCH_FILTERS"):
        await repository.search([0.0] * EMBEDDING_DIMENSIONS, filters=pending)


@pytest.mark.integration
async def test_exact_search_filters_reviewed_and_returns_stable_score() -> None:
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    values = _document_values(document_id, active_generation=None)
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[0] = 1.0
    chunk_values = _chunk_values(
        document_id,
        chunk_id,
        generation=1,
        state="ACTIVE",
        section_index=0,
        content_hash="c" * 64,
        embedding=vector,
    )
    engine = create_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                CorpusDocumentModel.__table__.insert().values(**values)
            )
            await connection.execute(
                CorpusChunkModel.__table__.insert().values(**chunk_values)
            )
            await connection.execute(
                CorpusDocumentModel.__table__.update()
                .where(CorpusDocumentModel.id == document_id)
                .values(
                    active_generation=1,
                    review_status="REVIEWED",
                    provenance_type="HUMAN_REVIEWED",
                    reviewed_by="search-test",
                    reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
        async with UnitOfWork() as uow:
            rows = await ExactVectorSearchRepository(uow._session).search(
                vector, limit=3
            )
            assert len(rows) == 1
            assert rows[0][0].id == chunk_id
            assert 0 <= rows[0][2] <= 1
            candidate = rows[0]
            assert "excerpt" in candidate
            assert not {
                "raw_content",
                "normalized_content",
                "embedding",
                "review_notes",
                "reviewed_by",
            }.intersection(candidate)
            assert candidate["language"] == "es"
            json.dumps(dict(candidate))
            await uow.rollback()
    finally:
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    CorpusDocumentModel.__table__.delete().where(
                        CorpusDocumentModel.id == document_id
                    )
                )
        finally:
            await engine.dispose()


@pytest.mark.integration
async def test_exact_search_language_filter_excludes_other_languages() -> None:
    document_ids = [uuid.uuid4(), uuid.uuid4()]
    chunk_ids = [uuid.uuid4(), uuid.uuid4()]
    languages = ["es", "pt"]
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[0] = 1.0
    engine = create_engine()
    try:
        async with engine.begin() as connection:
            for document_id, chunk_id, language in zip(
                document_ids, chunk_ids, languages, strict=True
            ):
                values = _document_values(document_id, active_generation=None)
                values["language"] = language
                values["external_id"] = f"language-{language}-{document_id.hex}"
                values["source_identifier"] = (
                    f"language/{language}/{document_id.hex}.txt"
                )
                await connection.execute(
                    CorpusDocumentModel.__table__.insert().values(**values)
                )
                await connection.execute(
                    CorpusChunkModel.__table__.insert().values(
                        **_chunk_values(
                            document_id,
                            chunk_id,
                            generation=1,
                            state="ACTIVE",
                            section_index=0,
                            content_hash=("c" if language == "es" else "d") * 64,
                            embedding=vector,
                        )
                    )
                )
                await connection.execute(
                    CorpusDocumentModel.__table__.update()
                    .where(CorpusDocumentModel.id == document_id)
                    .values(
                        active_generation=1,
                        review_status="REVIEWED",
                        provenance_type="HUMAN_REVIEWED",
                        reviewed_by="language-test",
                        reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                )
        async with UnitOfWork() as uow:
            filters = SearchFilters(
                document_type="decreto",
                document_subtype="designacion_transitoria",
                jurisdiction="nacion",
                language="es",
            )
            spanish = await ExactVectorSearchRepository(uow._session).search(
                vector, filters=filters, limit=5
            )
            assert {candidate["language"] for candidate in spanish} == {"es"}
            portuguese = await ExactVectorSearchRepository(uow._session).search(
                vector,
                filters=SearchFilters(
                    document_type="decreto",
                    document_subtype="designacion_transitoria",
                    jurisdiction="nacion",
                    language="pt",
                ),
                limit=5,
            )
            assert {candidate["language"] for candidate in portuguese} == {"pt"}
            both = await ExactVectorSearchRepository(uow._session).search(
                vector,
                filters=SearchFilters(
                    document_type="decreto",
                    document_subtype="designacion_transitoria",
                    jurisdiction="nacion",
                ),
                limit=5,
            )
            assert {candidate["language"] for candidate in both} >= {"es", "pt"}
            await uow.rollback()
    finally:
        async with engine.begin() as connection:
            for document_id in document_ids:
                await connection.execute(
                    CorpusDocumentModel.__table__.delete().where(
                        CorpusDocumentModel.id == document_id
                    )
                )
        await engine.dispose()
