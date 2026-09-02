"""Minimal unit of work for the isolated IMI dispositions RAG database."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.dispositions_pgvector_search import (
    DispositionsVectorSearchRepository,
)
from legal_ai.adapters.database.engine import get_session_factory


class DispositionsRagUnitOfWork:
    """Owns only a session and the read-only IMI vector-search repository."""

    def __init__(self) -> None:
        self._session: AsyncSession | None = None
        self._vector_search: DispositionsVectorSearchRepository | None = None

    async def __aenter__(self) -> DispositionsRagUnitOfWork:
        self._session = get_session_factory("imi_dispositions_rag")()
        await self._session.begin()
        self._vector_search = DispositionsVectorSearchRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self._session is None:
            return
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    @property
    def vector_search(self) -> DispositionsVectorSearchRepository:
        if self._vector_search is None:
            raise RuntimeError("DispositionsRagUnitOfWork not initialized")
        return self._vector_search

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("DispositionsRagUnitOfWork not initialized")
        return self._session
