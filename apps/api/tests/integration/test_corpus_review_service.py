from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.corpus_review import CorpusReviewService
from legal_ai.domain.corpus import CorpusDocument, ReviewStatus, sha256_text
from legal_ai.schemas.corpus_review import CorpusReviewRequest


@pytest.mark.integration
async def test_corpus_review_uses_cas_and_single_safe_audit() -> None:
    document_id = uuid.uuid4()
    source_identifier = f"review-{document_id}.txt"
    content = "ARTÃCULO 1Â°.- Documento para revisiÃ³n."
    document = CorpusDocument(
        id=document_id,
        source_identifier=source_identifier,
        raw_content=content,
        normalized_content=content,
        raw_content_hash=sha256_text(content),
        normalized_content_hash=sha256_text(content),
        external_id=f"review-{document_id}",
        source_name="filesystem",
        metadata={"pipeline_version": "005"},
    )
    try:
        async with UnitOfWork() as uow:
            await uow.corpus_documents.create(document)
        request = CorpusReviewRequest(
            document_id=document_id,
            approve=True,
            reviewed_by="integration-reviewer",
            expected_version=1,
        )
        async with UnitOfWork() as uow:
            result = await CorpusReviewService(uow).review(
                request, request_id="review-request-1"
            )
        assert result.status == ReviewStatus.REVIEWED.value
        assert result.review_version == 2

        with pytest.raises(ValueError, match="CORPUS_REVIEW_VERSION_MISMATCH"):
            async with UnitOfWork() as uow:
                await CorpusReviewService(uow).review(request)

        engine = create_engine()
        try:
            async with engine.connect() as connection:
                audit = await connection.execute(
                    text(
                        "SELECT count(*) FROM review_events "
                        "WHERE resource_type = 'CORPUS_DOCUMENT' "
                        "AND resource_id = :resource_id"
                    ),
                    {"resource_id": str(document_id)},
                )
                assert audit.scalar_one() == 1
        finally:
            await engine.dispose()
    finally:
        engine = create_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM review_events WHERE resource_type = "
                        "'CORPUS_DOCUMENT' AND resource_id = :resource_id"
                    ),
                    {"resource_id": str(document_id)},
                )
                await connection.execute(
                    text("DELETE FROM corpus_documents WHERE id = :document_id"),
                    {"document_id": document_id},
                )
        finally:
            await engine.dispose()
