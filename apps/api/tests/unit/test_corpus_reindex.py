from __future__ import annotations

import uuid

import pytest

from legal_ai.application.corpus_reindex import CorpusReindexService
from legal_ai.domain.corpus import CorpusDocument, sha256_text
from legal_ai.schemas.corpus_reindex import CorpusReindexRequest


def _document() -> CorpusDocument:
    content = "VISTO el expediente EX-1. ARTICULO 1.- Texto."
    return CorpusDocument(
        id=uuid.uuid4(),
        source_identifier="reindex-unit.txt",
        raw_content=content,
        normalized_content=content,
        raw_content_hash=sha256_text(content),
        normalized_content_hash=sha256_text(content),
        external_id="reindex-unit",
        source_name="filesystem",
        active_generation=1,
    )


@pytest.mark.asyncio
async def test_reindex_dry_run_is_deterministic_and_read_only(monkeypatch) -> None:
    service = CorpusReindexService(uow_factory=lambda: None)
    document = _document()
    monkeypatch.setattr(service, "_select", lambda request: _one(document))
    request = CorpusReindexRequest(document_ids=(document.id,))
    first = await service.dry_run(request)
    second = await service.dry_run(request)
    assert first.model_dump() == second.model_dump()
    assert first.execution_mode == "DRY_RUN"
    assert first.documents_reindexed == 0


@pytest.mark.asyncio
async def test_reindex_selection_paginates_beyond_repository_page_limit() -> None:
    documents = tuple(_document() for _ in range(1001))
    offsets: list[int] = []

    class _Repository:
        async def list(self, **kwargs):
            offset = int(kwargs["offset"])
            limit = int(kwargs["limit"])
            offsets.append(offset)
            return documents[offset : offset + limit]

    class _UnitOfWork:
        corpus_documents = _Repository()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    service = CorpusReindexService(uow_factory=_UnitOfWork)
    selected = await service._select(CorpusReindexRequest())

    assert len(selected) == 1001
    assert offsets == [0, 1000]


async def _one(document: CorpusDocument) -> tuple[CorpusDocument, ...]:
    return (document,)
