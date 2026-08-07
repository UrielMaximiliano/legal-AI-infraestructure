"""Ports for replaceable embedding providers and inference coordination."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from enum import IntEnum
from typing import Protocol, TypeVar


class InferencePriority(IntEnum):
    INTERACTIVE = 0
    SEARCH = 10
    BATCH_INGESTION = 20


class EmbeddingProvider(Protocol):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


T = TypeVar("T")


class InferenceCoordinationPort(Protocol):
    async def execute(
        self,
        priority: InferencePriority,
        operation: Callable[[], Awaitable[T]],
        *,
        timeout: float | None = None,
    ) -> T: ...
