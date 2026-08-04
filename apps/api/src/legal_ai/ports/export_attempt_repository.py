"""Port for export attempt history and idempotency lookups."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_ai.domain.enums import ExportFormat
from legal_ai.domain.export_attempt import ExportAttempt


class ExportAttemptRepository(Protocol):
    async def get_latest(self, export_id: UUID) -> ExportAttempt | None: ...

    async def get_latest_by_draft_key(
        self,
        draft_id: UUID,
        idempotency_key: str,
        export_format: ExportFormat | None = None,
    ) -> ExportAttempt | None: ...

    async def next_attempt_number(self, export_id: UUID) -> int: ...

    async def create(self, attempt: ExportAttempt) -> ExportAttempt: ...

    async def update(self, attempt: ExportAttempt) -> ExportAttempt: ...

    async def list_by_export(
        self, export_id: UUID, offset: int, limit: int
    ) -> tuple[list[ExportAttempt], int]: ...

    async def list_for_reconcile(self) -> list[ExportAttempt]: ...

    async def delete(self, attempt_id: UUID) -> None: ...
