"""PostgreSQL RAG E2E evidence; never runs against the operational database."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.corpus_models import (
    CorpusChunkModel,
    CorpusDocumentModel,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.models import (
    CaseFileModel,
    DocumentDraftModel,
    DocumentReviewModel,
    DocumentTemplateModel,
    EmployeeModel,
    ReviewEventModel,
)
from legal_ai.adapters.database.rag_models import (
    RagGenerationRunModel,
    RagRetrievedSourceModel,
    RagStructuredDraftModel,
)
from legal_ai.adapters.generation.fake_structured_generation import (
    FakeStructuredGenerationProvider,
)
from legal_ai.application.rag_evaluation import (
    HoldoutCase,
    HoldoutManifest,
    find_operational_holdout_leaks,
)
from legal_ai.application.rag_generation import (
    RagGenerationService,
    SQLAlchemyRagAuditStore,
)
from legal_ai.application.rag_retrieval import RagRetrievalService
from legal_ai.domain.corpus import CorpusIngestionStatus
from legal_ai.schemas.rag import RagDraftGenerationRequest

from .rag_postgres_support import run_alembic

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


class _Embedding:
    async def embed_query(self, query: str) -> list[float]:
        del query
        return [1.0, *([0.0] * 2559)]


@dataclass(frozen=True)
class _CorpusSeed:
    document_id: UUID
    chunk_id: UUID
    external_id: str


@dataclass(frozen=True)
class _CaseSeed:
    corpus: _CorpusSeed
    employee_id: UUID
    case_file_id: UUID
    template_id: UUID


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _seed(session: AsyncSession, *, with_case: bool) -> _CaseSeed:
    now = datetime.now(UTC)
    document_id = uuid4()
    chunk_id = uuid4()
    external_id = f"RAG-TEST-{uuid4().hex}"
    document = CorpusDocumentModel(
        id=document_id,
        external_id=external_id,
        title="Reviewed test decree",
        document_type="decreto",
        document_subtype="designacion_transitoria",
        jurisdiction="nacion",
        language="es",
        organization="test",
        source_name="isolated-test",
        source_identifier=f"test://{external_id}",
        raw_content="Reviewed legal antecedent",
        raw_content_hash=_hash(external_id + "raw"),
        normalized_content="Reviewed legal antecedent",
        normalized_content_hash=_hash(external_id + "normalized"),
        metadata_json={"evaluation_split": "INDEX_90", "source_label": "test"},
        provenance_type="HUMAN_REVIEWED",
        review_status="REVIEWED",
        review_version=1,
        reviewed_by="integration-test",
        reviewed_at=now,
        ingestion_status=CorpusIngestionStatus.INDEXED,
        embedding_status="EMBEDDED",
        created_by_pipeline_version="005-test",
        normalization_version="005-test",
        chunking_version="005-test",
        active_generation=1,
        created_at=now,
        updated_at=now,
    )
    chunk = CorpusChunkModel(
        id=chunk_id,
        document_id=document_id,
        generation=1,
        state="ACTIVE",
        section_type="CONSIDERANDO",
        section_index=0,
        paragraph_index=0,
        content="The reviewed antecedent supports the designation.",
        content_hash=_hash(external_id + "chunk"),
        token_count=8,
        embedding=[1.0, *([0.0] * 2559)],
        embedding_model="qwen3-embedding:4b-q4_K_M",
        embedding_dimensions=2560,
        normalization_version="005-test",
        chunking_version="005-test",
        metadata_json={"source_label": "test"},
        created_at=now,
        updated_at=now,
    )
    # The corpus models intentionally expose scalar foreign keys rather than
    # an ORM relationship. Flush parents explicitly so the real PostgreSQL FK
    # is exercised without relying on mapper insertion ordering.
    session.add(document)
    await session.flush()
    session.add(chunk)
    await session.flush()
    employee_id = uuid4()
    case_file_id = uuid4()
    template_id = uuid4()
    if with_case:
        session.add(
            EmployeeModel(
                id=employee_id,
                employee_number=f"RAG-{uuid4().hex[:12]}",
                first_name="RAG",
                last_name="Test",
                document_type="dni",
                document_number=uuid4().hex[:8],
                active=True,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            CaseFileModel(
                id=case_file_id,
                case_number=f"RAG-{uuid4().hex[:12]}",
                employee_id=employee_id,
                title="RAG integration case",
                description="Isolated integration case",
                case_type="designacion",
                status="draft",
                version=1,
                opened_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            DocumentTemplateModel(
                id=template_id,
                name=f"RAG template {uuid4().hex}",
                document_type="resolucion",
                version=1,
                body_template="{{ cargo }}",
                variables=["cargo"],
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
    return _CaseSeed(
        _CorpusSeed(document_id, chunk_id, external_id),
        employee_id,
        case_file_id,
        template_id,
    )


async def _cleanup(session: AsyncSession, seed: _CaseSeed) -> None:
    await session.execute(
        delete(ReviewEventModel).where(ReviewEventModel.draft_id.in_(
            select(DocumentDraftModel.id).where(
                DocumentDraftModel.case_file_id == seed.case_file_id
            )
        ))
    )
    await session.execute(
        delete(DocumentReviewModel).where(DocumentReviewModel.draft_id.in_(
            select(DocumentDraftModel.id).where(
                DocumentDraftModel.case_file_id == seed.case_file_id
            )
        ))
    )
    run_ids = select(RagGenerationRunModel.id).where(
        RagGenerationRunModel.case_file_id == seed.case_file_id
    )
    await session.execute(
        delete(RagStructuredDraftModel).where(RagStructuredDraftModel.run_id.in_(run_ids))
    )
    await session.execute(
        delete(RagRetrievedSourceModel).where(RagRetrievedSourceModel.run_id.in_(run_ids))
    )
    await session.execute(
        delete(RagGenerationRunModel).where(RagGenerationRunModel.id.in_(run_ids))
    )
    await session.execute(
        delete(DocumentDraftModel).where(
            DocumentDraftModel.case_file_id == seed.case_file_id
        )
    )
    await session.execute(
        delete(CorpusChunkModel).where(CorpusChunkModel.id == seed.corpus.chunk_id)
    )
    await session.execute(
        delete(CorpusDocumentModel).where(
            CorpusDocumentModel.id == seed.corpus.document_id
        )
    )
    if seed.template_id:
        await session.execute(
            delete(DocumentTemplateModel).where(
                DocumentTemplateModel.id == seed.template_id
            )
        )
    if seed.case_file_id:
        await session.execute(
            delete(CaseFileModel).where(CaseFileModel.id == seed.case_file_id)
        )
    if seed.employee_id:
        await session.execute(
            delete(EmployeeModel).where(EmployeeModel.id == seed.employee_id)
        )


@pytest.mark.asyncio
async def test_postgres_retrieval_is_exact_and_fail_closed() -> None:
    run_alembic("upgrade", "007")
    engine = create_engine()
    seed: _CaseSeed | None = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            seed = await _seed(session, with_case=False)
            await session.commit()
        retrieval = RagRetrievalService(
            embedding_provider=_Embedding(),
            max_chunks_per_document=2,
            max_chunks_per_section=1,
        )
        result = await retrieval.retrieve(
            "antecedente jurídico",
            filters={
                "document_type": "decreto",
                "document_subtype": "designacion_transitoria",
                "jurisdiction": "nacion",
                "review_status": "REVIEWED",
                "evaluation_split": "INDEX_90",
                "language": "es",
            },
            top_k=3,
            candidate_pool_size=3,
        )
        assert [source.external_id for source in result.sources] == [
            seed.corpus.external_id
        ]
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                update(CorpusDocumentModel)
                .where(CorpusDocumentModel.id == seed.corpus.document_id)
                .values(
                    review_status="PENDING_REVIEW",
                    provenance_type="AUTOMATED",
                    reviewed_by=None,
                    reviewed_at=None,
                )
            )
            await session.commit()
        closed = await retrieval.retrieve(
            "antecedente jurídico",
            filters={
                "document_type": "decreto",
                "document_subtype": "designacion_transitoria",
                "jurisdiction": "nacion",
                "review_status": "REVIEWED",
                "evaluation_split": "INDEX_90",
                "language": "es",
            },
            top_k=3,
            candidate_pool_size=3,
        )
        assert closed.sources == ()
    finally:
        if seed is not None:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await _cleanup(session, seed)
                await session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_generation_persists_review_and_replays_idempotently() -> None:
    run_alembic("upgrade", "007")
    engine = create_engine()
    seed: _CaseSeed | None = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            seed = await _seed(session, with_case=True)
            await session.commit()
        retrieval = RagRetrievalService(embedding_provider=_Embedding())
        service = RagGenerationService(
            retrieval=retrieval,
            provider=FakeStructuredGenerationProvider(),
            audit=SQLAlchemyRagAuditStore(),
        )
        request = RagDraftGenerationRequest(
            template_id=seed.template_id,
            case_file_id=seed.case_file_id,
            variables={"cargo": "Director"},
        )
        first = await service.generate(
            request, idempotency_key="rag-postgres-key-0001", request_id="rag-req-1"
        )
        second = await service.generate(
            request, idempotency_key="rag-postgres-key-0001", request_id="rag-req-2"
        )
        assert first.run.id == second.run.id
        assert first.draft is not None
        assert first.draft.status.value == "en_revision"
        async with AsyncSession(engine, expire_on_commit=False) as session:
            draft = await session.get(DocumentDraftModel, first.draft.id)
            review = await session.scalar(
                select(DocumentReviewModel).where(
                    DocumentReviewModel.draft_id == first.draft.id
                )
            )
            run_count = await session.scalar(
                select(RagGenerationRunModel.id).where(
                    RagGenerationRunModel.id == first.run.id
                )
            )
        assert draft is not None and draft.status == "en_revision"
        assert review is not None and review.status == "OPEN"
        assert run_count == first.run.id
    finally:
        if seed is not None:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await _cleanup(session, seed)
                await session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_holdout_guard_detects_operational_identity() -> None:
    run_alembic("upgrade", "007")
    engine = create_engine()
    seed: _CaseSeed | None = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            seed = await _seed(session, with_case=False)
            await session.commit()
        manifest = HoldoutManifest(
            dataset_version="holdout-test",
            split="HOLDOUT_10",
            source="isolated-test",
            cases=(
                HoldoutCase(
                    "holdout-1",
                    "opaque.pdf",
                    _hash(seed.corpus.external_id + "raw"),
                    seed.corpus.external_id,
                ),
            ),
        )
        assert await find_operational_holdout_leaks(manifest) > 0
    finally:
        if seed is not None:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await _cleanup(session, seed)
                await session.commit()
        await engine.dispose()
