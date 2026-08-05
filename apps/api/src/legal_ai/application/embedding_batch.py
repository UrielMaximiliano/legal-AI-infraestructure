"""Embedding batch orchestration kept outside persistence transactions."""

from __future__ import annotations

from collections.abc import Sequence

from legal_ai.domain.corpus import validate_embedding
from legal_ai.ports.embedding import (
    EmbeddingProvider,
    InferenceCoordinationPort,
    InferencePriority,
)


class EmbeddingBatchProcessor:
    """Submit one validated batch through the bounded inference coordinator."""

    def __init__(
        self,
        provider: EmbeddingProvider,
        coordinator: InferenceCoordinationPort,
        *,
        dimensions: int = 1024,
        timeout_seconds: float = 30.0,
    ) -> None:
        if dimensions != 1024 or timeout_seconds <= 0:
            raise ValueError("EMBEDDING_BATCH_CONFIGURATION_INVALID")
        self._provider = provider
        self._coordinator = coordinator
        self._dimensions = dimensions
        self._timeout_seconds = timeout_seconds

    async def embed(
        self,
        texts: Sequence[str],
        *,
        priority: InferencePriority = InferencePriority.BATCH_INGESTION,
    ) -> list[list[float]]:
        if isinstance(texts, str) or not texts:
            raise ValueError("EMBEDDING_BATCH_INPUT_INVALID")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("EMBEDDING_BATCH_INPUT_INVALID")

        async def operation() -> list[list[float]]:
            return await self._provider.embed_documents(tuple(texts))

        vectors = await self._coordinator.execute(
            priority,
            operation,
            timeout=self._timeout_seconds,
        )
        if len(vectors) != len(texts):
            raise ValueError("EMBEDDING_COUNT_MISMATCH")
        for vector in vectors:
            validate_embedding(vector, self._dimensions)
        return vectors
