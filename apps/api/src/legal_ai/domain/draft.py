"""Draft domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from legal_ai.domain.enums import DraftStatus, TransitionAction


@dataclass
class Draft:
    """Borrador de documento."""

    id: UUID
    template_id: UUID
    case_file_id: UUID
    title: str
    status: DraftStatus
    version: int
    generation_number: int
    context_snapshot: dict[str, object]
    context_hash: str
    created_at: datetime
    updated_at: datetime
    content: str | None = None
    variables_used: dict[str, str] = field(default_factory=dict)
    parent_draft_id: UUID | None = None
    observations: str | None = None
    request_id: str | None = None
    finalized_by: str | None = None
    finalized_at: datetime | None = None
    finalization_notes: str | None = None
    final_snapshot: dict[str, object] | None = None
    final_snapshot_sha256: str | None = None

    def is_finalized(self) -> bool:
        """Return whether this draft has an immutable final snapshot."""
        return self.finalized_at is not None

    def can_finalize(self) -> bool:
        """Return whether finalization metadata can be written once."""
        return self.status == DraftStatus.APROBADO and not self.is_finalized()


@dataclass
class DraftTransition:
    """Transición de estado de un borrador."""

    id: UUID
    draft_id: UUID
    from_status: DraftStatus
    to_status: DraftStatus
    action: TransitionAction
    created_at: datetime
    observations: str | None = None
    performed_by: str | None = None


VALID_TRANSITIONS: dict[DraftStatus, set[DraftStatus]] = {
    DraftStatus.GENERADO: {DraftStatus.EN_REVISION},
    DraftStatus.EN_REVISION: {DraftStatus.APROBADO, DraftStatus.RECHAZADO},
    DraftStatus.RECHAZADO: {DraftStatus.EN_REVISION},
    DraftStatus.APROBADO: set(),
    DraftStatus.SUPERSEDED: set(),
}

ACTION_MAP: dict[TransitionAction, tuple[DraftStatus, DraftStatus]] = {
    TransitionAction.SEND_TO_REVIEW: (DraftStatus.GENERADO, DraftStatus.EN_REVISION),
    TransitionAction.APPROVE: (DraftStatus.EN_REVISION, DraftStatus.APROBADO),
    TransitionAction.REJECT: (DraftStatus.EN_REVISION, DraftStatus.RECHAZADO),
}


def can_transition(from_status: DraftStatus, to_status: DraftStatus) -> bool:
    """Check if a state transition is valid."""
    return to_status in VALID_TRANSITIONS.get(from_status, set())
