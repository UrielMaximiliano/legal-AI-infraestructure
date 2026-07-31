"""Case status history repository port (interface)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.case_status_history import CaseStatusHistory


class CaseStatusHistoryRepository(Protocol):
    """Protocol defining case status history repository operations."""

    async def create(self, entry: CaseStatusHistory) -> CaseStatusHistory: ...

    async def list_by_case_file(
        self, case_file_id: UUID
    ) -> list[CaseStatusHistory]: ...
