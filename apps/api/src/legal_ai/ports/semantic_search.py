"""Ports for exact vector search and minimized audit persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from legal_ai.domain.semantic_search import SemanticSearchCandidate, SemanticSearchRun


class VectorSearchPort(Protocol):
    async def search(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int,
        minimum_score: float,
        filters: Mapping[str, str] | None = None,
        reviewed_only: bool = True,
    ) -> Sequence[SemanticSearchCandidate | Mapping[str, object]]: ...


class SemanticSearchRunRepository(Protocol):
    async def record(self, run: SemanticSearchRun) -> None: ...
