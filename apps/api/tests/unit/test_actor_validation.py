"""Actor and idempotency validation tests for 004."""

import pytest
from pydantic import ValidationError

from legal_ai.schemas.finalization import FinalizeDraftRequest
from legal_ai.schemas.review import ReviewCreateRequest
from legal_ai.schemas.validation import validate_idempotency_key


def test_actor_is_trimmed_and_preserves_case_and_unicode() -> None:
    request = FinalizeDraftRequest(
        expected_version=1,
        finalized_by="  Árbitro_01@Mesa  ",
    )
    assert request.finalized_by == "Árbitro_01@Mesa"


@pytest.mark.parametrize("value", ["", "   ", "a" * 101, "actor/1", "actor\\1"])
def test_invalid_actor_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        FinalizeDraftRequest(expected_version=1, finalized_by=value)


def test_review_actor_fields_are_textual_and_not_identifiers() -> None:
    request = ReviewCreateRequest(
        draft_version=1,
        expected_version=1,
        opened_by="Reviewer-01@organismo",
    )
    assert request.opened_by == "Reviewer-01@organismo"
    assert "actor_id" not in ReviewCreateRequest.model_fields


@pytest.mark.parametrize("value", ["short", "a" * 101, "unsafe/key-value"])
def test_idempotency_key_requires_safe_16_to_100_characters(value: str) -> None:
    with pytest.raises(ValueError):
        validate_idempotency_key(value)


def test_idempotency_key_accepts_contractual_symbols() -> None:
    assert validate_idempotency_key("review.op_01~safe-key") == "review.op_01~safe-key"
