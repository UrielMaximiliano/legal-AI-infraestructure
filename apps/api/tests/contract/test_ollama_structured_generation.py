from __future__ import annotations

import httpx
import pytest

from legal_ai.adapters.ollama.structured_generation import (
    OllamaStructuredGenerationProvider,
)
from legal_ai.ports.structured_generation import StructuredGenerationError


@pytest.mark.asyncio
async def test_chat_contract_uses_json_schema_and_never_streams() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.read()
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"message": {"content": '{"schema_version":1}'}},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://ollama.test"
    )
    provider = OllamaStructuredGenerationProvider(
        base_url="https://ollama.test",
        api_token="secret-token",
        client=client,
    )
    try:
        result = await provider.generate_structured(
            system_message="system",
            user_message="user",
            schema={"type": "object"},
        )
    finally:
        await client.aclose()
    assert result == {"schema_version": 1}
    assert b'"stream":false' in bytes(captured["payload"])
    assert b'"format":{"type":"object"}' in bytes(captured["payload"])
    assert captured["authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_chat_retries_transient_failure_and_parses_fenced_json() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={"message": {"content": "```json\n{\"ok\":true}\n```"}},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://ollama.test"
    )
    provider = OllamaStructuredGenerationProvider(
        base_url="https://ollama.test",
        api_token="secret-token",
        client=client,
        max_retries=1,
    )
    try:
        result = await provider.generate_structured(
            system_message="system",
            user_message="user",
            schema={"type": "object"},
        )
    finally:
        await client.aclose()
    assert result == {"ok": True}
    assert calls == 2


@pytest.mark.asyncio
async def test_chat_rejects_remote_http_without_token() -> None:
    with pytest.raises(ValueError, match="INSECURE_OLLAMA_ENDPOINT"):
        OllamaStructuredGenerationProvider(
            base_url="http://remote.example",
            api_token="secret-token",
        )


@pytest.mark.asyncio
async def test_chat_translates_authentication_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://ollama.test"
    )
    provider = OllamaStructuredGenerationProvider(
        base_url="https://ollama.test",
        api_token="secret-token",
        client=client,
    )
    try:
        with pytest.raises(StructuredGenerationError) as exc_info:
            await provider.generate_structured(
                system_message="system",
                user_message="user",
                schema={"type": "object"},
            )
    finally:
        await client.aclose()
    assert exc_info.value.code == "OLLAMA_AUTHENTICATION_FAILED"
