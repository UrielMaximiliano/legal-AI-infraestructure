"""Designation repository port."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.designation_data import DesignationData


class DesignationRepository(Protocol):
    """Interface for designation data access."""

    async def create(self, designation: DesignationData) -> DesignationData: ...

    async def get_by_case_file_id(
        self, case_file_id: UUID
    ) -> DesignationData | None: ...

    async def update(self, designation: DesignationData) -> DesignationData: ...
