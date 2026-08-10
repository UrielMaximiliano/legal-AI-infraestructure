"""Ports used by the RAG application layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

from legal_ai.domain.rag import RagGenerationRun, RagRetrievedSource
from legal_ai.domain.semantic_search import SemanticSearchCandidate


class RagVectorSearchPort(Protocol):
    async def search(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int,
        minimum_score: float,
        filters: Mapping[str, str],
        evaluation_split: str,
    ) -> Sequence[SemanticSearchCandidate]: ...


class RagAuditRepository(Protocol):
    async def create_run(self, run: RagGenerationRun) -> None: ...

    async def update_run(self, run: RagGenerationRun) -> None: ...

    async def create_sources(
        self, run_id: UUID, sources: Sequence[RagRetrievedSource]
    ) -> None: ...


class RagClock(Protocol):
    def now(self) -> Any: ...


class RagUnitOfWorkFactory(Protocol):
    def __call__(self) -> Any: ...


Operation = Callable[[], Awaitable[Any]]
