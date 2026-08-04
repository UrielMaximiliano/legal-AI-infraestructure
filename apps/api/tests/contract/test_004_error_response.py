"""004 error-envelope compatibility and sanitization tests."""

import re
from unittest.mock import MagicMock

import pytest

from legal_ai.api.exceptions import domain_error_handler
from legal_ai.domain.errors import OpenBlockingCommentsError
from legal_ai.schemas.errors import ErrorResponse


def test_error_response_contains_003_flat_and_004_nested_shape() -> None:
    payload = ErrorResponse(
        error_code="OPEN_BLOCKING_COMMENTS",
        message="La revisión tiene comentarios bloqueantes abiertos",
        request_id="req-004",
    ).model_dump()
    assert payload["error_code"] == payload["error"]["code"]
    assert payload["request_id"] == payload["error"]["request_id"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^ ]+Z", payload["timestamp"])
    assert payload["error"]["timestamp"].endswith("Z")


@pytest.mark.anyio
async def test_domain_error_is_sanitized_and_keeps_request_id() -> None:
    request = MagicMock()
    request.state.request_id = "req-004"
    response = await domain_error_handler(request, OpenBlockingCommentsError())
    payload = response.body.decode()
    assert response.status_code == 409
    assert "req-004" in payload
    assert "stack" not in payload.lower()
    assert "path" not in payload.lower()
