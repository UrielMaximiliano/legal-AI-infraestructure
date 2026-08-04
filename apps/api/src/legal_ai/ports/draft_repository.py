"""Draft repository port."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus


class DraftRepository(Protocol):
    """Interface for draft data access."""

    async def create(self, draft: Draft) -> Draft: ...

    async def get_by_id(self, draft_id: UUID) -> Draft | None: ...

    async def get_by_id_for_update(self, draft_id: UUID) -> Draft | None: ...

    async def list_by_case_file(
        self,
        case_file_id: UUID,
        status: str | None,
        skip: int,
        limit: int,
    ) -> tuple[list[Draft], int]: ...

    async def update_with_optimistic_lock(
        self, draft: Draft, expected_version: int
    ) -> Draft | None: ...

    async def update(self, draft: Draft, expected_version: int) -> Draft | None: ...

    async def update_status(
        self, draft_id: UUID, new_status: DraftStatus, version: int
    ) -> Draft | None: ...

    async def update_finalization(
        self,
        draft_id: UUID,
        expected_version: int,
        finalized_by: str,
        finalized_at: object,
        finalization_notes: str | None,
        final_snapshot: dict[str, object],
        final_snapshot_sha256: str,
    ) -> Draft | None: ...
