"""Append-only audit event port."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.review_event import ReviewEvent


class ReviewEventRepository(Protocol):
    async def create(self, event: ReviewEvent) -> ReviewEvent: ...

    async def list_by_review(
        self, review_id: UUID, offset: int, limit: int
    ) -> tuple[list[ReviewEvent], int]: ...

    async def get_orphan_detection(self, fingerprint: str) -> ReviewEvent | None: ...

    async def get_reconciliation_run(self, run_id: UUID) -> ReviewEvent | None: ...
