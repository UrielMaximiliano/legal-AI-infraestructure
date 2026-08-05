from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.corpus_review import CorpusReviewService
from legal_ai.domain.corpus import CorpusDocument, sha256_text
from legal_ai.schemas.corpus_review import CorpusReviewRequest


@pytest.mark.integration
async def test_concurrent_review_has_one_cas_winner() -> None:
    document_id = uuid.uuid4()
    source = f"review-concurrent-{document_id}.txt"
    content = "ARTICULO 1.- Concurrencia de revision."
    document = CorpusDocument(
        id=document_id,
        source_identifier=source,
        raw_content=content,
        normalized_content=content,
        raw_content_hash=sha256_text(content),
        normalized_content_hash=sha256_text(content),
        external_id=str(document_id),
        source_name="filesystem",
    )
    try:
        async with UnitOfWork() as uow:
            await uow.corpus_documents.create(document)

        async def approve(request_id: str):
            async with UnitOfWork() as uow:
                return await CorpusReviewService(uow).review(
                    CorpusReviewRequest(
                        document_id=document_id,
                        approve=True,
                        reviewed_by=request_id,
                        expected_version=1,
                    ),
                    request_id=request_id,
                )

        results = await asyncio.gather(
            approve("reviewer-a"), approve("reviewer-b"), return_exceptions=True
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert sum(
            isinstance(result, ValueError)
            and "CORPUS_REVIEW_VERSION_MISMATCH" in str(result)
            for result in results
        ) == 1
    finally:
        engine = create_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM review_events WHERE resource_id = :resource_id"
                    ),
                    {"resource_id": str(document_id)},
                )
                await connection.execute(
                    text("DELETE FROM corpus_documents WHERE id = :document_id"),
                    {"document_id": document_id},
                )
        finally:
            await engine.dispose()
