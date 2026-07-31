"""Case file repository port (interface)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from legal_ai.domain.case_file import CaseFile


class CaseFileRepository(Protocol):
    """Protocol defining case file repository operations."""

    async def create(self, case_file: CaseFile) -> CaseFile: ...

    async def get_by_id(self, case_file_id: UUID) -> CaseFile | None: ...

    async def get_by_case_number(self, number: str) -> CaseFile | None: ...

    async def list(
        self,
        page: int,
        page_size: int,
        query: str | None = None,
        employee_id: UUID | None = None,
        status: str | None = None,
        case_type: str | None = None,
        opened_from: datetime | None = None,
        opened_to: datetime | None = None,
    ) -> tuple[list[CaseFile], int]: ...

    async def update(self, case_file: CaseFile) -> CaseFile: ...
