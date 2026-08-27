"""Unit checks for corpus readiness query construction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from legal_ai.adapters.database.corpus_document_repository import (
    SQLAlchemyCorpusDocumentRepository,
)


@pytest.mark.asyncio
async def test_readiness_count_does_not_assume_document_taxonomy() -> None:
    session = AsyncMock()
    session.scalar.return_value = 9000

    count = await SQLAlchemyCorpusDocumentRepository(
        session
    ).count_eligible_reviewed_documents()

    assert count == 9000
    statement = session.scalar.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "evaluation_split" in sql
    assert "document_type" not in sql
    assert "document_subtype" not in sql
    assert "jurisdiction" not in sql
