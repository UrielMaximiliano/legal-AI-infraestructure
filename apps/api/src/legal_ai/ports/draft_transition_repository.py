"""Draft transition repository port."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.draft import DraftTransition


class DraftTransitionRepository(Protocol):
    """Interface for draft transition data access."""

    async def create(self, transition: DraftTransition) -> DraftTransition: ...

    async def list_by_draft(self, draft_id: UUID) -> list[DraftTransition]: ...
