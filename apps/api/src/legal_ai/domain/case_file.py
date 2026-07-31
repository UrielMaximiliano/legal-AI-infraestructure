"""Case file domain model and state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from legal_ai.domain.enums import CaseStatus, CaseType

# Exactly 10 valid transitions as defined in spec
VALID_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.DRAFT: {CaseStatus.UNDER_REVIEW},
    CaseStatus.UNDER_REVIEW: {CaseStatus.IN_PROCESS, CaseStatus.DRAFT},
    CaseStatus.IN_PROCESS: {CaseStatus.SUBMITTED, CaseStatus.UNDER_REVIEW},
    CaseStatus.SUBMITTED: {CaseStatus.APPROVED, CaseStatus.REJECTED},
    CaseStatus.APPROVED: {CaseStatus.ARCHIVED},
    CaseStatus.REJECTED: {CaseStatus.UNDER_REVIEW, CaseStatus.ARCHIVED},
    CaseStatus.ARCHIVED: set(),  # terminal
}

# Constant for initial history changed_by
TRANSITIONS_INITIAL_HISTORY_CHANGED_BY = "system"


def can_transition(from_status: CaseStatus, to_status: CaseStatus) -> bool:
    """Check if a transition from one status to another is allowed."""
    return to_status in VALID_TRANSITIONS.get(from_status, set())


@dataclass
class CaseFile:
    """Case file domain entity."""

    id: UUID
    case_number: str
    employee_id: UUID
    title: str
    case_type: CaseType
    status: CaseStatus = CaseStatus.DRAFT
    version: int = 1
    description: str | None = None
    opened_at: datetime = field(default_factory=datetime.now)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    closed_at: datetime | None = None
