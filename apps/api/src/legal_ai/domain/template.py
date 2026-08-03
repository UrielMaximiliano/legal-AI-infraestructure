"""Template domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from legal_ai.domain.enums import TemplateDocumentType


@dataclass
class Template:
    """Plantilla de documento versionada."""

    id: UUID
    name: str
    document_type: TemplateDocumentType
    version: int
    body_template: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    variables: list[str] = field(default_factory=list)
