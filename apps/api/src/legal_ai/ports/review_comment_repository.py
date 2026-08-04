"""Ports for non-destructive review comments."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.review_comment import ReviewComment


class ReviewCommentRepository(Protocol):
    async def get_by_id(self, comment_id: UUID) -> ReviewComment | None: ...

    async def create(self, comment: ReviewComment) -> ReviewComment: ...

    async def update(
        self, comment: ReviewComment, expected_version: int
    ) -> ReviewComment | None: ...

    async def list_by_review(
        self, review_id: UUID, offset: int, limit: int
    ) -> tuple[list[ReviewComment], int]: ...

    async def count_open_blocking(self, review_id: UUID) -> int: ...
