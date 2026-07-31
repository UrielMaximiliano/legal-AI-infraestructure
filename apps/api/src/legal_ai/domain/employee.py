"""Employee domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from legal_ai.domain.enums import DocumentType


@dataclass
class Employee:
    """Employee domain entity."""

    id: UUID
    employee_number: str
    first_name: str
    last_name: str
    document_type: DocumentType
    document_number: str
    cuil: str | None = None
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    department: str | None = None
    active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
