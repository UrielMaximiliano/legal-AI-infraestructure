"""Shared request validation rules for actors and idempotency keys."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import field_validator

SAFE_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._~-]{16,100}$")


def validate_actor(value: Any) -> str | None:
    """Trim and validate a textual audit actor without authenticating it."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("actor must be a string")
    actor = value.strip()
    if not 1 <= len(actor) <= 100:
        raise ValueError("actor must contain between 1 and 100 characters")
    allowed_symbols = {" ", ".", "-", "_", "@"}
    if any(
        unicodedata.category(character)[0] not in {"L", "N", "M"}
        and character not in allowed_symbols
        for character in actor
    ):
        raise ValueError("actor contains unsupported characters")
    return actor


def validate_idempotency_key(value: Any) -> str:
    """Validate a safe 16–100 character Idempotency-Key."""
    if not isinstance(value, str) or SAFE_IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise ValueError("Idempotency-Key must contain 16–100 safe characters")
    return value


class ActorValidated:
    """Mixin for Pydantic models that contain textual audit actor fields."""

    _validate_actor = field_validator(
        "opened_by",
        "submitted_by",
        "decided_by",
        "author",
        "actor",
        "resolved_by",
        "finalized_by",
        "exported_by",
        mode="before",
        check_fields=False,
    )(validate_actor)
