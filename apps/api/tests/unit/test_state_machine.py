"""Unit tests for state machine."""

from legal_ai.domain.case_file import (
    TRANSITIONS_INITIAL_HISTORY_CHANGED_BY,
    VALID_TRANSITIONS,
    can_transition,
)
from legal_ai.domain.enums import CaseStatus


class TestValidTransitions:
    """Tests for valid transitions."""

    def test_draft_to_under_review(self):
        assert can_transition(CaseStatus.DRAFT, CaseStatus.UNDER_REVIEW)

    def test_under_review_to_in_process(self):
        assert can_transition(CaseStatus.UNDER_REVIEW, CaseStatus.IN_PROCESS)

    def test_under_review_to_draft(self):
        assert can_transition(CaseStatus.UNDER_REVIEW, CaseStatus.DRAFT)

    def test_in_process_to_submitted(self):
        assert can_transition(CaseStatus.IN_PROCESS, CaseStatus.SUBMITTED)

    def test_in_process_to_under_review(self):
        assert can_transition(CaseStatus.IN_PROCESS, CaseStatus.UNDER_REVIEW)

    def test_submitted_to_approved(self):
        assert can_transition(CaseStatus.SUBMITTED, CaseStatus.APPROVED)

    def test_submitted_to_rejected(self):
        assert can_transition(CaseStatus.SUBMITTED, CaseStatus.REJECTED)

    def test_rejected_to_under_review(self):
        assert can_transition(CaseStatus.REJECTED, CaseStatus.UNDER_REVIEW)

    def test_approved_to_archived(self):
        assert can_transition(CaseStatus.APPROVED, CaseStatus.ARCHIVED)

    def test_rejected_to_archived(self):
        assert can_transition(CaseStatus.REJECTED, CaseStatus.ARCHIVED)


class TestInvalidTransitions:
    """Tests for invalid transitions."""

    def test_same_state_invalid(self):
        assert not can_transition(CaseStatus.DRAFT, CaseStatus.DRAFT)

    def test_archived_terminal(self):
        assert not can_transition(CaseStatus.ARCHIVED, CaseStatus.DRAFT)
        assert not can_transition(CaseStatus.ARCHIVED, CaseStatus.UNDER_REVIEW)
        assert not can_transition(CaseStatus.ARCHIVED, CaseStatus.APPROVED)

    def test_approved_cannot_go_to_draft(self):
        assert not can_transition(CaseStatus.APPROVED, CaseStatus.DRAFT)

    def test_draft_cannot_go_to_approved(self):
        assert not can_transition(CaseStatus.DRAFT, CaseStatus.APPROVED)

    def test_draft_cannot_go_to_archived(self):
        assert not can_transition(CaseStatus.DRAFT, CaseStatus.ARCHIVED)


class TestTransitionCount:
    """Tests for transition count."""

    def test_exactly_10_transitions(self):
        total = sum(len(targets) for targets in VALID_TRANSITIONS.values())
        assert total == 10


class TestInitialHistoryChangedBy:
    """Tests for initial history changed_by constant."""

    def test_initial_history_changed_by_is_system(self):
        assert TRANSITIONS_INITIAL_HISTORY_CHANGED_BY == "system"
