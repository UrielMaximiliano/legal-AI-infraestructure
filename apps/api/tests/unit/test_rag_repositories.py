from __future__ import annotations

from uuid import uuid4

import pytest

from legal_ai.adapters.database.rag_models import RagGenerationRunModel
from legal_ai.adapters.database.rag_repositories import (
    SQLAlchemyRagEvaluationRepository,
    SQLAlchemyRagGenerationRunRepository,
    SQLAlchemyRagRetrievedSourceRepository,
    SQLAlchemyRagStructuredDraftRepository,
)
from legal_ai.domain.rag import (
    RagGenerationRun,
    RagRetrievedSource,
    RagSourceDisposition,
    sha256_text,
)
from legal_ai.schemas.rag import RagStructuredDraft


class _Session:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    def add_all(self, values: list[object]) -> None:
        self.added.extend(values)

    async def flush(self) -> None:
        return None


def _run() -> RagGenerationRun:
    return RagGenerationRun(
        id=uuid4(),
        case_file_id=uuid4(),
        template_id=uuid4(),
        request_hash=sha256_text("request"),
        query_hash=sha256_text("query"),
        idempotency_key_hash=sha256_text("key"),
        request_id="request-1",
    )


def _source(run: RagGenerationRun) -> RagRetrievedSource:
    excerpt = "Reviewed evidence"
    return RagRetrievedSource(
        document_id=run.case_file_id,
        chunk_id=uuid4(),
        external_id="DOC-1",
        title="Reviewed decree",
        publication_date="2025-01-01",
        section_type="CONSIDERANDO",
        generation=1,
        similarity_score=0.9,
        retrieval_rank=1,
        citation_id="SRC-001",
        excerpt=excerpt,
        disposition=RagSourceDisposition.SELECTED,
        context_rank=1,
        content_hash=sha256_text(excerpt),
    )


def _structured() -> RagStructuredDraft:
    return RagStructuredDraft.model_validate(
        {
            "schema_version": 1,
            "title": "Draft",
            "visto": [{"text": "Visto", "citation_ids": ["SRC-001"]}],
            "considerandos": [
                {"text": "Considerando", "citation_ids": ["SRC-001"]}
            ],
            "dispositive_intro": "Por ello",
            "articles": [{"number": 1, "text": "Designar", "citation_ids": []}],
            "closing": "Comunicar",
            "authority": "Autoridad",
            "signature": "Pendiente",
            "sources": [
                {
                    "citation_id": "SRC-001",
                    "external_id": "DOC-1",
                    "title": "Reviewed decree",
                    "publication_date": "2025-01-01",
                    "section_type": "CONSIDERANDO",
                }
            ],
            "warnings": ["NO VINCULANTE - REVISION HUMANA OBLIGATORIA"],
        }
    )


@pytest.mark.asyncio
async def test_rag_repositories_build_allowlisted_models() -> None:
    session = _Session()
    run = _run()
    run_repo = SQLAlchemyRagGenerationRunRepository(session)
    model = run_repo._to_model(run)
    assert isinstance(model, RagGenerationRunModel)
    assert run_repo._to_domain(model).request_hash == run.request_hash

    source_repo = SQLAlchemyRagRetrievedSourceRepository(session)
    await source_repo.create_many(run.id, (_source(run),))
    structured_repo = SQLAlchemyRagStructuredDraftRepository(session)
    draft_id = uuid4()
    await structured_repo.create(
        run_id=run.id, draft_id=draft_id, structured=_structured()
    )
    evaluation_repo = SQLAlchemyRagEvaluationRepository(session)
    await evaluation_repo.create(
        {
            "evaluation_run_id": uuid4(),
            "case_id": "H-1",
            "holdout_sha256": sha256_text("holdout"),
            "mode": "FAKE",
            "configuration_hash": sha256_text("config"),
            "schema_valid": True,
            "required_sections_present": True,
            "duration_ms": 1,
        }
    )
    assert len(session.added) == 3
