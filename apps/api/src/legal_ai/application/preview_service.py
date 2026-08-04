"""Read-only draft preview application service."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from uuid import UUID

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.renderers.canonical_html_renderer import (
    SafeCanonicalHtmlRenderer,
)
from legal_ai.application.canonical_document import CanonicalDocumentBuilder
from legal_ai.domain.enums import DraftStatus
from legal_ai.domain.errors import (
    ConcurrentModification004Error,
    DraftNotApprovedError,
    DraftNotFound004Error,
)
from legal_ai.observability.logging import log_event


@dataclass(frozen=True)
class PreviewResult:
    html: str
    sha256: str
    draft_version: int


class PreviewService:
    """Render a preview without persisting HTML or creating export rows."""

    def __init__(
        self,
        uow: UnitOfWork,
        renderer: SafeCanonicalHtmlRenderer | None = None,
    ) -> None:
        self._uow = uow
        self._renderer = renderer or SafeCanonicalHtmlRenderer()

    async def preview(self, draft_id: UUID, draft_version: int) -> PreviewResult:
        started = time.perf_counter()
        draft = await self._uow.drafts.get_by_id(draft_id)
        if draft is None:
            raise DraftNotFound004Error(details={"draft_id": str(draft_id)})
        if draft.status != DraftStatus.APROBADO:
            raise DraftNotApprovedError()
        if draft.version != draft_version:
            raise ConcurrentModification004Error(
                details={"expected_version": draft_version}
            )
        if draft.is_finalized():
            snapshot = draft.final_snapshot or {}
        else:
            snapshot = CanonicalDocumentBuilder.build_preview(draft).as_snapshot()
        html_text = self._renderer.render(snapshot)
        log_event(
            "preview_render_completed",
            draft_id=draft.id,
            format="html",
            export_version=None,
            size_bytes=len(html_text.encode("utf-8")),
            sha256=hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            phase="render",
            result="success",
        )
        return PreviewResult(
            html=html_text,
            sha256=hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
            draft_version=draft_version,
        )
