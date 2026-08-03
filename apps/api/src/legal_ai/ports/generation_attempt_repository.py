"""Generation attempt repository port."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.generation_attempt import GenerationAttempt


class GenerationAttemptRepository(Protocol):
    """Interface for generation attempt data access."""

    async def create(self, attempt: GenerationAttempt) -> GenerationAttempt: ...

    async def get_by_idempotency_key(self, key: str) -> GenerationAttempt | None: ...

    async def get_by_id(self, attempt_id: UUID) -> GenerationAttempt | None: ...

    async def list_by_case_file(
        self, case_file_id: UUID
    ) -> list[GenerationAttempt]: ...

    async def update(self, attempt: GenerationAttempt) -> GenerationAttempt: ...

    async def delete_by_idempotency_key(self, key: str) -> None: ...

    async def cleanup_expired(self, window_hours: int = 24) -> int: ...
