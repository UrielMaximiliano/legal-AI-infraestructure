"""Template domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class Template:
    """Plantilla de documento versionada."""

    id: UUID
    name: str
    document_type: str
    version: int
    body_template: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    organ_emisor: str | None = None
    normativa: str | None = None
    description: str | None = None
    variables: list[str] = field(default_factory=list)
    template_version_id: UUID | None = None
    status: str = "PUBLISHED"
    revision: int = 1
    fields: list[dict[str, Any]] = field(default_factory=list)
    rules: list[dict[str, Any]] = field(default_factory=list)
    instructions: str | None = None
    blocks: list[dict[str, Any]] = field(default_factory=list)
    extraction_warnings: list[str] = field(default_factory=list)
    author: str | None = None
