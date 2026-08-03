"""Template repository port."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.template import Template


class TemplateRepository(Protocol):
    """Interface for template data access."""

    async def create(self, template: Template) -> Template: ...

    async def get_by_id(self, template_id: UUID) -> Template | None: ...

    async def get_active_version(
        self, name: str, document_type: str
    ) -> Template | None: ...

    async def list_active(
        self,
        document_type: str | None,
        search: str | None,
        skip: int,
        limit: int,
    ) -> tuple[list[Template], int]: ...

    async def update(self, template: Template) -> Template: ...

    async def deactivate_all_versions(self, name: str, document_type: str) -> None: ...
