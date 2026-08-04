"""Ports for versioned human reviews."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.review import DocumentReview


class ReviewRepository(Protocol):
    async def get_by_id(self, review_id: UUID) -> DocumentReview | None: ...

    async def get_current(
        self, draft_id: UUID, draft_version: int
    ) -> DocumentReview | None: ...

    async def get_latest_for_draft(self, draft_id: UUID) -> DocumentReview | None: ...

    async def create(self, review: DocumentReview) -> DocumentReview: ...

    async def update(
        self, review: DocumentReview, expected_version: int
    ) -> DocumentReview | None: ...

    async def list_by_draft(
        self, draft_id: UUID, draft_version: int, offset: int, limit: int
    ) -> tuple[list[DocumentReview], int]: ...
