"""Employee repository port (interface)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.employee import Employee


class EmployeeRepository(Protocol):
    """Protocol defining employee repository operations."""

    async def create(self, employee: Employee) -> Employee: ...

    async def get_by_id(self, employee_id: UUID) -> Employee | None: ...

    async def get_by_employee_number(self, number: str) -> Employee | None: ...

    async def get_by_document(
        self, doc_type: str, doc_number: str
    ) -> Employee | None: ...

    async def get_by_cuil(self, cuil: str) -> Employee | None: ...

    async def list(
        self,
        page: int,
        page_size: int,
        query: str | None = None,
        active: bool | None = None,
        department: str | None = None,
    ) -> tuple[list[Employee], int]: ...

    async def update(self, employee: Employee) -> Employee: ...

    async def deactivate(self, employee_id: UUID) -> Employee | None: ...
