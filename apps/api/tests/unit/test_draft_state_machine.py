"""Unit tests for draft state machine."""

from legal_ai.domain.draft import (
    ACTION_MAP,
    VALID_TRANSITIONS,
    can_transition,
)
from legal_ai.domain.enums import DraftStatus, TransitionAction


class TestDraftValidTransitions:
    """Tests for valid draft transitions."""

    def test_generado_to_en_revision(self):
        assert can_transition(DraftStatus.GENERADO, DraftStatus.EN_REVISION)

    def test_en_revision_to_aprobado(self):
        assert can_transition(DraftStatus.EN_REVISION, DraftStatus.APROBADO)

    def test_en_revision_to_rechazado(self):
        assert can_transition(DraftStatus.EN_REVISION, DraftStatus.RECHAZADO)

    def test_rechazado_to_en_revision(self):
        assert can_transition(DraftStatus.RECHAZADO, DraftStatus.EN_REVISION)


class TestDraftInvalidTransitions:
    """Tests for invalid draft transitions."""

    def test_generado_to_aprobado_invalid(self):
        assert not can_transition(DraftStatus.GENERADO, DraftStatus.APROBADO)

    def test_generado_to_rechazado_invalid(self):
        assert not can_transition(DraftStatus.GENERADO, DraftStatus.RECHAZADO)

    def test_generado_to_superseded_invalid(self):
        assert not can_transition(DraftStatus.GENERADO, DraftStatus.SUPERSEDED)

    def test_aprobado_terminal(self):
        assert not can_transition(DraftStatus.APROBADO, DraftStatus.GENERADO)
        assert not can_transition(DraftStatus.APROBADO, DraftStatus.EN_REVISION)
        assert not can_transition(DraftStatus.APROBADO, DraftStatus.RECHAZADO)
        assert not can_transition(DraftStatus.APROBADO, DraftStatus.SUPERSEDED)

    def test_superseded_terminal(self):
        assert not can_transition(DraftStatus.SUPERSEDED, DraftStatus.GENERADO)
        assert not can_transition(DraftStatus.SUPERSEDED, DraftStatus.EN_REVISION)
        assert not can_transition(DraftStatus.SUPERSEDED, DraftStatus.APROBADO)
        assert not can_transition(DraftStatus.SUPERSEDED, DraftStatus.RECHAZADO)

    def test_same_state_invalid(self):
        assert not can_transition(DraftStatus.GENERADO, DraftStatus.GENERADO)
        assert not can_transition(DraftStatus.EN_REVISION, DraftStatus.EN_REVISION)
        assert not can_transition(DraftStatus.APROBADO, DraftStatus.APROBADO)

    def test_en_revision_to_generado_invalid(self):
        assert not can_transition(DraftStatus.EN_REVISION, DraftStatus.GENERADO)

    def test_rechazado_to_aprobado_invalid(self):
        assert not can_transition(DraftStatus.RECHAZADO, DraftStatus.APROBADO)


class TestActionMap:
    """Tests for action mapping."""

    def test_send_to_review_maps_correctly(self):
        from_status, to_status = ACTION_MAP[TransitionAction.SEND_TO_REVIEW]
        assert from_status == DraftStatus.GENERADO
        assert to_status == DraftStatus.EN_REVISION

    def test_approve_maps_correctly(self):
        from_status, to_status = ACTION_MAP[TransitionAction.APPROVE]
        assert from_status == DraftStatus.EN_REVISION
        assert to_status == DraftStatus.APROBADO

    def test_reject_maps_correctly(self):
        from_status, to_status = ACTION_MAP[TransitionAction.REJECT]
        assert from_status == DraftStatus.EN_REVISION
        assert to_status == DraftStatus.RECHAZADO


class TestValidTransitionsCount:
    """Tests for transition count."""

    def test_exactly_4_transitions(self):
        total = sum(len(targets) for targets in VALID_TRANSITIONS.values())
        assert total == 4


class TestDraftStatusValues:
    """Tests for DraftStatus enum values."""

    def test_all_statuses_exist(self):
        assert DraftStatus.GENERADO == "generado"
        assert DraftStatus.EN_REVISION == "en_revision"
        assert DraftStatus.APROBADO == "aprobado"
        assert DraftStatus.RECHAZADO == "rechazado"
        assert DraftStatus.SUPERSEDED == "superseded"

    def test_five_statuses(self):
        assert len(DraftStatus) == 5


class TestTransitionActionValues:
    """Tests for TransitionAction enum values."""

    def test_all_actions_exist(self):
        assert TransitionAction.SEND_TO_REVIEW == "send_to_review"
        assert TransitionAction.APPROVE == "approve"
        assert TransitionAction.REJECT == "reject"
        assert TransitionAction.EDIT_CONTENT == "edit_content"

    def test_four_actions(self):
        assert len(TransitionAction) == 4
