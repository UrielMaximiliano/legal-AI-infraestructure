"""Unit tests for document-generation Ollama client error handling."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from legal_ai.application.ollama_client import (
    OllamaClient,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)


class _ClientContext:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.post = AsyncMock()
        if isinstance(response, Exception):
            self.post.side_effect = response
        else:
            self.post.return_value = response

    async def __aenter__(self) -> _ClientContext:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


def _response(status: int, payload: object) -> httpx.Response:
    request = httpx.Request("POST", "http://ollama/api/generate")
    return httpx.Response(status, json=payload, request=request)


@pytest.mark.asyncio
async def test_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _ClientContext(_response(200, {"response": "texto", "total_duration": 2}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)

    result = await OllamaClient().generate("prompt")

    assert result.content == "texto"
    assert result.total_duration == 2
    headers = fake.post.await_args.kwargs["headers"]
    assert headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
async def test_upstream_errors_are_safe(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    fake = _ClientContext(_response(status, {"error": "secret upstream detail"}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)

    with pytest.raises(OllamaResponseError) as captured:
        await OllamaClient().generate("private prompt")

    message = str(captured.value)
    assert "private prompt" not in message
    assert "secret upstream detail" not in message


@pytest.mark.asyncio
async def test_timeout_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _ClientContext(httpx.ReadTimeout("timeout"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)

    with pytest.raises(OllamaTimeoutError):
        await OllamaClient().generate("prompt")


@pytest.mark.asyncio
async def test_connection_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _ClientContext(httpx.ConnectError("token=test-token"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)

    with pytest.raises(OllamaUnavailableError) as captured:
        await OllamaClient().generate("private prompt")

    assert "test-token" not in str(captured.value)
    assert "private prompt" not in str(captured.value)


@pytest.mark.asyncio
async def test_invalid_json_and_empty_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = httpx.Response(
        200,
        content=b"not-json",
        request=httpx.Request("POST", "http://ollama/api/generate"),
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _ClientContext(invalid))
    with pytest.raises(OllamaUnavailableError):
        await OllamaClient().generate("prompt")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _ClientContext(_response(200, {"response": ""})),
    )
    with pytest.raises(OllamaResponseError):
        await OllamaClient().generate("prompt")
