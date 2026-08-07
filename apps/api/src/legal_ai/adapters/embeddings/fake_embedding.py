"""Deterministic, offline embedding provider for tests and dry-run planning."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Sequence

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS


class FakeEmbeddingError(RuntimeError):
    """Sanitized configurable fake failure."""


class FakeEmbeddingProvider:
    """Produces stable finite vectors without network, tokens or corpus logging."""

    def __init__(
        self,
        *,
        dimensions: int = EMBEDDING_DIMENSIONS,
        failure: str | None = None,
        failure_mode: str | None = None,
        invalid_vector: str | None = None,
        delay_seconds: float = 0.0,
        timeout_error: bool = False,
        fail_after: int | None = None,
    ) -> None:
        if dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"EMBEDDING_DIMENSIONS debe ser {EMBEDDING_DIMENSIONS}"
            )
        if delay_seconds < 0:
            raise ValueError("FAKE_EMBEDDING_DELAY_INVALID")
        self.dimensions = dimensions
        self.failure = failure or failure_mode
        self.invalid_vector = invalid_vector
        self.delay_seconds = delay_seconds
        self.timeout_error = timeout_error
        self.fail_after = fail_after
        self.calls = 0

    def _vector(self, text: str) -> list[float]:
        if not text:
            raise FakeEmbeddingError("EMBEDDING_INPUT_EMPTY")
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        for index in range(self.dimensions):
            byte = digest[index % len(digest)]
            values.append((byte / 127.5) - 1.0)
        if self.invalid_vector == "empty":
            values = []
        elif self.invalid_vector == "wrong_dimension":
            values = values[:-1]
        elif self.invalid_vector == "nan":
            values[0] = math.nan
        elif self.invalid_vector == "infinite":
            values[0] = math.inf
        if not values:
            raise FakeEmbeddingError("EMBEDDING_VECTOR_EMPTY")
        if len(values) != self.dimensions:
            raise FakeEmbeddingError("EMBEDDING_DIMENSIONS_MISMATCH")
        if not all(math.isfinite(value) for value in values):
            raise FakeEmbeddingError("EMBEDDING_VECTOR_INVALID")
        return values

    async def _before_call(self) -> None:
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.timeout_error or self.failure in {"timeout", "FAKE_EMBEDDING_TIMEOUT"}:
            raise FakeEmbeddingError("FAKE_EMBEDDING_TIMEOUT")
        if self.failure:
            raise FakeEmbeddingError(self.failure)
        if self.fail_after is not None and self.calls > self.fail_after:
            raise FakeEmbeddingError("FAKE_EMBEDDING_FAILURE")

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            raise FakeEmbeddingError("EMBEDDING_INPUT_EMPTY")
        await self._before_call()
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        await self._before_call()
        return self._vector(text)

    async def health_check(self) -> dict[str, object]:
        await self._before_call()
        return {"status": "ok", "model": "fake", "dimensions": self.dimensions}
