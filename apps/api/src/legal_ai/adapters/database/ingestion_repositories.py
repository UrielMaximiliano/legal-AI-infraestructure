"""Repositories for runs, failures and embedding batches."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.domain.ingestion import (
    EmbeddingBatch,
    EmbeddingBatchStatus,
    IngestionFailure,
    IngestionRun,
    IngestionRunStatus,
    IngestionRunType,
    configuration_hash_for_snapshot,
    sanitize_configuration_snapshot,
)
from legal_ai.ports.corpus_source import sanitize_source_identifier

from .ingestion_models import (
    EmbeddingBatchModel,
    IngestionFailureModel,
    IngestionRunModel,
)


class SQLAlchemyIngestionRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: IngestionRun) -> IngestionRun:
        source_identifier = run.source_identifier.strip()
        if not source_identifier:
            raise ValueError("INGESTION_SOURCE_IDENTIFIER_REQUIRED")
        if not run.configuration_hash:
            raise ValueError("INGESTION_CONFIGURATION_HASH_REQUIRED")
        snapshot = sanitize_configuration_snapshot(dict(run.configuration_snapshot))
        if snapshot and run.configuration_hash != configuration_hash_for_snapshot(
            snapshot
        ):
            raise ValueError("INGESTION_CONFIGURATION_HASH_MISMATCH")
        model = IngestionRunModel(
            id=run.id,
            run_id=run.run_id,
            run_type=run.run_type.value,
            status=run.status,
            source_identifier=source_identifier,
            configuration_hash=run.configuration_hash,
            configuration_snapshot=snapshot,
            counts=dict(run.counts),
            started_at=run.started_at,
            finished_at=run.finished_at,
            resumed_at=run.resumed_at,
            resume_count=run.resume_count,
            heartbeat_at=run.heartbeat_at,
            error_code=run.error_code,
            error_summary=run.error_summary,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get(self, run_id: str) -> IngestionRun | None:
        result = await self._session.execute(
            select(IngestionRunModel).where(IngestionRunModel.run_id == run_id)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def update(self, run: IngestionRun) -> IngestionRun:
        result = await self._session.execute(
            select(IngestionRunModel).where(IngestionRunModel.run_id == run.run_id)
        )
        model = result.scalars().first()
        if model is None:
            raise ValueError("INGESTION_RUN_NOT_FOUND")
        model.status = run.status
        model.source_identifier = run.source_identifier.strip()
        model.configuration_hash = run.configuration_hash
        model.configuration_snapshot = sanitize_configuration_snapshot(
            dict(run.configuration_snapshot)
        )
        model.counts = dict(run.counts)
        model.started_at = run.started_at  # type: ignore[assignment]
        model.finished_at = run.finished_at
        model.resumed_at = run.resumed_at
        model.resume_count = run.resume_count
        model.heartbeat_at = run.heartbeat_at
        model.error_code = run.error_code
        model.error_summary = run.error_summary
        await self._session.flush()
        return self._to_domain(model)

    @staticmethod
    def _to_domain(model: IngestionRunModel) -> IngestionRun:
        raw_counts = model.counts or {}
        parsed_count = raw_counts.get("parsed_count", 0)
        chunked_count = raw_counts.get("chunked_count", 0)
        return IngestionRun(
            id=model.id,
            run_id=model.run_id,
            run_type=IngestionRunType(model.run_type),
            status=IngestionRunStatus(model.status),
            processed_documents=(parsed_count if type(parsed_count) is int else 0),
            processed_chunks=(chunked_count if type(chunked_count) is int else 0),
            started_at=model.started_at,
            finished_at=model.finished_at,
            resumed_at=model.resumed_at,
            resume_count=model.resume_count,
            error_code=model.error_code,
            source_identifier=model.source_identifier,
            configuration_hash=model.configuration_hash,
            configuration_snapshot=dict(model.configuration_snapshot or {}),
            counts={
                str(key): value
                for key, value in (model.counts or {}).items()
                if type(value) is int
            },
            heartbeat_at=model.heartbeat_at,
            error_summary=model.error_summary,
        )


class SQLAlchemyIngestionFailureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, failure: IngestionFailure) -> IngestionFailure:
        source_identifier = None
        if failure.source_identifier is not None:
            source_identifier = sanitize_source_identifier(failure.source_identifier)
        model = IngestionFailureModel(
            id=failure.id,
            ingestion_run_id=failure.ingestion_run_id,
            stage=failure.stage,
            error_code=failure.error_code,
            message=" ".join(failure.message.split())[:500],
            retryable=failure.retryable,
            source_identifier=source_identifier,
            document_id=failure.document_id,
            batch_id=failure.batch_id,
            created_at=failure.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return failure

    async def get(self, failure_id: uuid.UUID) -> IngestionFailure | None:
        model = await self._session.get(IngestionFailureModel, failure_id)
        if model is None:
            return None
        return IngestionFailure(
            id=model.id,
            ingestion_run_id=model.ingestion_run_id,
            stage=model.stage,
            error_code=model.error_code,
            message=model.message,
            retryable=model.retryable,
            source_identifier=model.source_identifier,
            document_id=model.document_id,
            batch_id=model.batch_id,
            created_at=model.created_at,
        )


class SQLAlchemyEmbeddingBatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, batch: EmbeddingBatch) -> EmbeddingBatch:
        model = EmbeddingBatchModel(
            id=batch.id,
            ingestion_run_id=batch.ingestion_run_id,
            generation=batch.generation,
            batch_index=batch.batch_index,
            status=batch.status,
            chunk_ids=[str(value) for value in batch.chunk_ids],
            input_count=batch.input_count,
            embedding_model=batch.embedding_model,
            embedding_dimensions=batch.embedding_dimensions,
            attempt_count=batch.attempt_count,
            started_at=batch.started_at,
            finished_at=batch.finished_at,
            error_code=batch.error_code,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get(self, batch_id: uuid.UUID) -> EmbeddingBatch | None:
        model = await self._session.get(EmbeddingBatchModel, batch_id)
        return self._to_domain(model) if model else None

    async def list_for_run(
        self, ingestion_run_id: uuid.UUID, generation: int
    ) -> tuple[EmbeddingBatch, ...]:
        result = await self._session.execute(
            select(EmbeddingBatchModel)
            .where(
                EmbeddingBatchModel.ingestion_run_id == ingestion_run_id,
                EmbeddingBatchModel.generation == generation,
            )
            .order_by(EmbeddingBatchModel.batch_index)
        )
        return tuple(self._to_domain(model) for model in result.scalars())

    async def list_all_for_run(
        self, ingestion_run_id: uuid.UUID
    ) -> tuple[EmbeddingBatch, ...]:
        result = await self._session.execute(
            select(EmbeddingBatchModel)
            .where(EmbeddingBatchModel.ingestion_run_id == ingestion_run_id)
            .order_by(EmbeddingBatchModel.generation, EmbeddingBatchModel.batch_index)
        )
        return tuple(self._to_domain(model) for model in result.scalars())

    async def update(self, batch: EmbeddingBatch) -> EmbeddingBatch:
        model = await self._session.get(EmbeddingBatchModel, batch.id)
        if model is None:
            return await self.create(batch)
        model.status = batch.status
        model.chunk_ids = [str(value) for value in batch.chunk_ids]
        model.input_count = batch.input_count
        model.embedding_model = batch.embedding_model
        model.embedding_dimensions = batch.embedding_dimensions
        model.attempt_count = batch.attempt_count
        model.started_at = batch.started_at
        model.finished_at = batch.finished_at
        model.error_code = batch.error_code
        await self._session.flush()
        return self._to_domain(model)

    @staticmethod
    def _to_domain(model: EmbeddingBatchModel) -> EmbeddingBatch:
        return EmbeddingBatch(
            id=model.id,
            ingestion_run_id=model.ingestion_run_id,
            generation=model.generation,
            batch_index=model.batch_index,
            input_count=model.input_count,
            status=EmbeddingBatchStatus(model.status),
            chunk_ids=tuple(uuid.UUID(value) for value in model.chunk_ids),
            embedding_model=model.embedding_model,
            embedding_dimensions=model.embedding_dimensions,
            attempt_count=model.attempt_count,
            started_at=model.started_at,
            finished_at=model.finished_at,
            error_code=model.error_code,
        )


IngestionRunRepository = SQLAlchemyIngestionRunRepository
IngestionFailureRepository = SQLAlchemyIngestionFailureRepository
EmbeddingBatchRepository = SQLAlchemyEmbeddingBatchRepository
