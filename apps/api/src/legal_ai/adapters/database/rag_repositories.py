"""Allowlisted repositories for RAG audit persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.rag_models import (
    RagEvaluationResultModel,
    RagGenerationRunModel,
    RagRetrievedSourceModel,
    RagStructuredDraftModel,
)
from legal_ai.domain.rag import (
    RagGenerationRun,
    RagGenerationStatus,
    RagRetrievedSource,
    sha256_text,
)
from legal_ai.schemas.rag import RagStructuredDraft


class SQLAlchemyRagGenerationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: RagGenerationRun) -> None:
        self._session.add(self._to_model(run))
        await self._session.flush()

    async def update(self, run: RagGenerationRun) -> None:
        await self._session.execute(
            update(RagGenerationRunModel)
            .where(RagGenerationRunModel.id == run.id)
            .values(**self._values(run))
        )
        await self._session.flush()

    async def get(self, run_id: UUID) -> RagGenerationRun | None:
        result = await self._session.execute(
            select(RagGenerationRunModel).where(RagGenerationRunModel.id == run_id)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def find_by_idempotency_hash(self, key_hash: str) -> RagGenerationRun | None:
        result = await self._session.execute(
            select(RagGenerationRunModel)
            .where(RagGenerationRunModel.idempotency_key_hash == key_hash)
            .order_by(RagGenerationRunModel.created_at.desc())
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    @staticmethod
    def _values(run: RagGenerationRun) -> dict[str, Any]:
        return {
            "generation_attempt_id": run.generation_attempt_id,
            "draft_id": run.draft_id,
            "context_hash": run.context_hash,
            "prompt_hash": run.prompt_hash,
            "status": str(run.status),
            "retrieved_count": run.retrieved_count,
            "selected_count": run.selected_count,
            "context_bytes": run.context_bytes,
            "context_tokens_estimate": run.context_tokens_estimate,
            "schema_repair_count": run.schema_repair_count,
            "retrieval_duration_ms": run.retrieval_duration_ms,
            "generation_duration_ms": run.generation_duration_ms,
            "validation_duration_ms": run.validation_duration_ms,
            "total_duration_ms": run.total_duration_ms,
            "error_code": run.error_code,
            "updated_at": run.updated_at,
            "finished_at": run.finished_at,
        }

    @classmethod
    def _to_model(cls, run: RagGenerationRun) -> RagGenerationRunModel:
        values = cls._values(run)
        return RagGenerationRunModel(
            id=run.id,
            case_file_id=run.case_file_id,
            template_id=run.template_id,
            idempotency_key_hash=run.idempotency_key_hash,
            request_hash=run.request_hash,
            query_hash=run.query_hash,
            embedding_model=run.embedding_model,
            embedding_dimensions=run.embedding_dimensions,
            generation_model=run.generation_model,
            prompt_version=run.prompt_version,
            schema_version=run.schema_version,
            top_k=run.top_k,
            candidate_pool_size=run.candidate_pool_size,
            minimum_score=run.minimum_score,
            request_id=run.request_id,
            **values,
        )

    @staticmethod
    def _to_domain(model: RagGenerationRunModel) -> RagGenerationRun:
        return RagGenerationRun(
            id=model.id,
            generation_attempt_id=model.generation_attempt_id,
            draft_id=model.draft_id,
            case_file_id=model.case_file_id,
            template_id=model.template_id,
            idempotency_key_hash=model.idempotency_key_hash,
            request_hash=model.request_hash,
            query_hash=model.query_hash,
            context_hash=model.context_hash,
            prompt_hash=model.prompt_hash,
            status=RagGenerationStatus(model.status),
            embedding_model=model.embedding_model,
            embedding_dimensions=model.embedding_dimensions,
            generation_model=model.generation_model,
            prompt_version=model.prompt_version,
            schema_version=model.schema_version,
            top_k=model.top_k,
            candidate_pool_size=model.candidate_pool_size,
            minimum_score=float(model.minimum_score)
            if model.minimum_score is not None
            else None,
            retrieved_count=model.retrieved_count,
            selected_count=model.selected_count,
            context_bytes=model.context_bytes,
            context_tokens_estimate=model.context_tokens_estimate,
            schema_repair_count=model.schema_repair_count,
            retrieval_duration_ms=model.retrieval_duration_ms,
            generation_duration_ms=model.generation_duration_ms,
            validation_duration_ms=model.validation_duration_ms,
            total_duration_ms=model.total_duration_ms,
            error_code=model.error_code,
            request_id=model.request_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
            finished_at=model.finished_at,
        )


class SQLAlchemyRagRetrievedSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(
        self, run_id: UUID, sources: Sequence[RagRetrievedSource]
    ) -> None:
        self._session.add_all(
            [
                RagRetrievedSourceModel(
                    run_id=run_id,
                    document_id=source.document_id,
                    chunk_id=source.chunk_id,
                    citation_id=source.citation_id,
                    retrieval_rank=source.retrieval_rank,
                    context_rank=source.context_rank,
                    similarity_score=source.similarity_score,
                    disposition=str(source.disposition),
                    section_type=source.section_type,
                    generation=source.generation,
                    content_hash=source.content_hash or sha256_text(source.excerpt),
                )
                for source in sources
            ]
        )
        await self._session.flush()

    async def list_by_run(self, run_id: UUID) -> list[RagRetrievedSourceModel]:
        result = await self._session.execute(
            select(RagRetrievedSourceModel)
            .where(RagRetrievedSourceModel.run_id == run_id)
            .order_by(RagRetrievedSourceModel.retrieval_rank)
        )
        return list(result.scalars().all())


class SQLAlchemyRagStructuredDraftRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        run_id: UUID,
        draft_id: UUID,
        structured: RagStructuredDraft,
    ) -> None:
        self._session.add(
            RagStructuredDraftModel(
                run_id=run_id,
                draft_id=draft_id,
                schema_version=structured.schema_version,
                content_json=structured.model_dump(mode="json"),
                content_hash=sha256_text(structured.model_dump_json()),
                citation_count=len(structured.sources),
                warning_count=len(structured.warnings),
            )
        )
        await self._session.flush()

    async def get_by_run(self, run_id: UUID) -> RagStructuredDraftModel | None:
        result = await self._session.execute(
            select(RagStructuredDraftModel).where(
                RagStructuredDraftModel.run_id == run_id
            )
        )
        return result.scalars().first()


class SQLAlchemyRagEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, values: Mapping[str, Any]) -> None:
        self._session.add(RagEvaluationResultModel(**dict(values)))
        await self._session.flush()
