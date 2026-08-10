"""Port for structured generative providers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class StructuredGenerationError(Exception):
    """Provider failure carrying only a stable public code."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class StructuredGenerationProvider(Protocol):
    model: str

    async def generate_structured(
        self,
        *,
        system_message: str,
        user_message: str,
        schema: Mapping[str, Any],
        temperature: float = 0.1,
        context: Sequence[Mapping[str, Any]] = (),
    ) -> Mapping[str, Any]: ...

    async def health_check(self) -> Mapping[str, Any]: ...
