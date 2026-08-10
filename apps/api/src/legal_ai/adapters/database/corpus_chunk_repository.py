"""PostgreSQL repository for staged and active corpus chunks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.domain.corpus import CorpusChunk

from .corpus_mappers import corpus_chunk_from_model, corpus_chunk_to_model
from .corpus_models import CorpusChunkModel


class SQLAlchemyCorpusChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, chunk: CorpusChunk) -> CorpusChunk:
        model = corpus_chunk_to_model(chunk)
        self._session.add(model)
        await self._session.flush()
        return corpus_chunk_from_model(model)

    async def upsert(self, chunk: CorpusChunk) -> CorpusChunk:
        result = await self._session.execute(
            select(CorpusChunkModel).where(CorpusChunkModel.id == chunk.id)
        )
        model = result.scalars().first()
        if model is None:
            return await self.create(chunk)
        model.state = chunk.state
        model.content = chunk.content
        model.content_hash = chunk.content_hash
        model.embedding = list(chunk.embedding) if chunk.embedding is not None else None
        model.embedding_model = chunk.embedding_model
        model.embedding_dimensions = chunk.embedding_dimensions
        await self._session.flush()
        return corpus_chunk_from_model(model)

    async def update(self, chunk: CorpusChunk) -> CorpusChunk:
        return await self.upsert(chunk)

    async def get(self, chunk_id: uuid.UUID) -> CorpusChunk | None:
        model = await self._session.get(CorpusChunkModel, chunk_id)
        return corpus_chunk_from_model(model) if model else None

    async def list_active(
        self, document_id: uuid.UUID, generation: int
    ) -> Sequence[CorpusChunk]:
        result = await self._session.execute(
            select(CorpusChunkModel)
            .where(
                CorpusChunkModel.document_id == document_id,
                CorpusChunkModel.generation == generation,
                CorpusChunkModel.state == "ACTIVE",
            )
            .order_by(CorpusChunkModel.section_index, CorpusChunkModel.paragraph_index)
        )
        return tuple(corpus_chunk_from_model(model) for model in result.scalars())

    async def list_generation(
        self, document_id: uuid.UUID, generation: int
    ) -> Sequence[CorpusChunk]:
        result = await self._session.execute(
            select(CorpusChunkModel)
            .where(
                CorpusChunkModel.document_id == document_id,
                CorpusChunkModel.generation == generation,
            )
            .order_by(CorpusChunkModel.section_index, CorpusChunkModel.paragraph_index)
        )
        return tuple(corpus_chunk_from_model(model) for model in result.scalars())

    async def activate_generation(
        self, document_id: uuid.UUID, generation: int
    ) -> None:
        """Atomically publish one staged generation inside the caller's UoW."""

        if generation <= 0:
            raise ValueError("CORPUS_GENERATION_INVALID")
        await self._session.execute(
            update(CorpusChunkModel)
            .where(
                CorpusChunkModel.document_id == document_id,
                CorpusChunkModel.state == "ACTIVE",
                CorpusChunkModel.generation != generation,
            )
            .values(state="SUPERSEDED")
        )
        result = await self._session.execute(
            update(CorpusChunkModel)
            .where(
                CorpusChunkModel.document_id == document_id,
                CorpusChunkModel.generation == generation,
                CorpusChunkModel.state == "STAGED",
            )
            .values(state="ACTIVE")
        )
        if getattr(result, "rowcount", 0) == 0:
            raise ValueError("CORPUS_GENERATION_NOT_FOUND")

    async def activate_generations(
        self, document_ids: Sequence[uuid.UUID], generation: int
    ) -> None:
        """Publish a prevalidated batch in the caller's short transaction."""

        ids = tuple(document_ids)
        if generation <= 0:
            raise ValueError("CORPUS_GENERATION_INVALID")
        if not ids:
            return
        await self._session.execute(
            update(CorpusChunkModel)
            .where(
                CorpusChunkModel.document_id.in_(ids),
                CorpusChunkModel.state == "ACTIVE",
                CorpusChunkModel.generation != generation,
            )
            .values(state="SUPERSEDED")
        )
        result = await self._session.execute(
            update(CorpusChunkModel)
            .where(
                CorpusChunkModel.document_id.in_(ids),
                CorpusChunkModel.generation == generation,
                CorpusChunkModel.state == "STAGED",
            )
            .values(state="ACTIVE")
        )
        if getattr(result, "rowcount", 0) == 0:
            raise ValueError("CORPUS_GENERATION_NOT_FOUND")


CorpusChunkRepository = SQLAlchemyCorpusChunkRepository
