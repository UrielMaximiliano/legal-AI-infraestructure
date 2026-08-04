"""Port for scoped review idempotency claims."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.review import ReviewOperationRequest


class ReviewOperationRequestRepository(Protocol):
    async def get(
        self, operation: str, resource_id: UUID, idempotency_key: str
    ) -> ReviewOperationRequest | None: ...

    async def create(
        self, request: ReviewOperationRequest
    ) -> ReviewOperationRequest: ...

    async def update(
        self, request: ReviewOperationRequest
    ) -> ReviewOperationRequest: ...

    async def delete_expired(
        self, operation: str, resource_id: UUID, idempotency_key: str
    ) -> None: ...
