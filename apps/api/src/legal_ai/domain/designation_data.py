"""DesignationData domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass
class DesignationData:
    """Datos de designación para expedientes de tipo designación."""

    id: UUID
    case_file_id: UUID
    position_name: str
    created_at: datetime
    updated_at: datetime
    organizational_unit: str | None = None
    start_date: date | None = None
    legal_basis: str | None = None
    appointing_authority: str | None = None
    salary_category: str | None = None
    work_schedule: str | None = None
    observations: str | None = None
