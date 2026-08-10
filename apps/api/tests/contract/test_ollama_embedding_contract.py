import json

import httpx
import pytest

from legal_ai.adapters.ollama_embedding import (
    OllamaEmbeddingAdapter,
    OllamaEmbeddingError,
)


def make_adapter(handler):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://ollama.test")
    return OllamaEmbeddingAdapter(
        base_url="https://ollama.test", api_token="secret", client=client
    ), client


@pytest.mark.asyncio
async def test_request_bearer_batch_and_dimension() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert request.url.path == "/api/embed"
        payload = json.loads(request.content)
        assert payload["options"] == {"num_ctx": 2048}
        return httpx.Response(200, json={"embeddings": [[0.0] * 2560, [1.0] * 2560]})

    adapter, client = make_adapter(handler)
    try:
        result = await adapter.embed_documents(["a", "b"])
        assert len(result) == 2 and len(result[0]) == 2560
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_native_endpoint_uses_configured_context_length() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["options"] == {"num_ctx": 4096}
        return httpx.Response(200, json={"embeddings": [[0.0] * 2560]})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://ollama.test")
    adapter = OllamaEmbeddingAdapter(
        base_url="https://ollama.test",
        api_token="secret",
        context_length=4096,
        client=client,
    )
    try:
        assert len(await adapter.embed_query("synthetic")) == 2560
    finally:
        await client.aclose()


@pytest.mark.parametrize("context_length", [0, -1, 32769])
def test_invalid_embedding_context_length_is_rejected(context_length: int) -> None:
    with pytest.raises(ValueError, match="CONTEXT_LENGTH"):
        OllamaEmbeddingAdapter(
            base_url="https://ollama.test",
            api_token="secret",
            context_length=context_length,
        )


@pytest.mark.asyncio
async def test_legacy_endpoint_uses_sequential_prompts() -> None:
    prompts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embeddings"
        payload = request.content
        assert b'"input"' not in payload
        assert b'"dimensions"' not in payload
        decoded = json.loads(payload)
        assert "options" not in decoded
        prompts.append(decoded["prompt"])
        return httpx.Response(200, json={"embedding": [float(len(prompts))] * 2560})

    adapter, client = make_adapter(handler)
    adapter = OllamaEmbeddingAdapter(
        base_url="https://ollama.test",
        api_token="secret",
        endpoint="/api/embeddings",
        client=client,
    )
    try:
        result = await adapter.embed_documents(["first", "second"])
        assert prompts == ["first", "second"]
        assert [vector[0] for vector in result] == [1.0, 2.0]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_reverse_proxy_prefix_is_preserved() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ollama/api/embeddings"
        return httpx.Response(200, json={"embedding": [0.0] * 2560})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        transport=transport, base_url="https://ollama.test/ollama"
    )
    adapter = OllamaEmbeddingAdapter(
        base_url="https://ollama.test/ollama",
        api_token="secret",
        endpoint="/api/embeddings",
        client=client,
    )
    try:
        result = await adapter.embed_query("synthetic")
        assert len(result) == 2560
    finally:
        await client.aclose()


def test_unknown_embedding_endpoint_is_rejected() -> None:
    with pytest.raises(ValueError, match="ENDPOINT"):
        OllamaEmbeddingAdapter(
            base_url="https://ollama.test",
            api_token="secret",
            endpoint="/api/unknown",
        )


@pytest.mark.asyncio
async def test_invalid_response_and_no_retry_for_auth() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "secret"})

    adapter, client = make_adapter(handler)
    try:
        with pytest.raises(OllamaEmbeddingError) as exc_info:
            await adapter.embed_query("a")
        assert exc_info.value.code == "OLLAMA_AUTHENTICATION_FAILED"
        assert calls == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_count_dimension_nan_and_empty_are_rejected() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.0] * 2560]})

    adapter, client = make_adapter(handler)
    try:
        with pytest.raises(OllamaEmbeddingError):
            adapter._validate([[float("nan")] * 2560], 1)
        with pytest.raises(OllamaEmbeddingError):
            await adapter.embed_documents([])
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 422])
async def test_client_errors_are_sanitized_and_not_retried(status: int) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": "sensitive"})

    adapter, client = make_adapter(handler)
    try:
        with pytest.raises(OllamaEmbeddingError):
            await adapter.embed_query("x")
        assert calls == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_transient_errors_are_retried_with_bounded_attempts(status: int) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    adapter, client = make_adapter(handler)
    try:
        with pytest.raises(OllamaEmbeddingError):
            await adapter.embed_query("x")
        assert calls == 3
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 504])
async def test_gateway_errors_succeed_after_one_retry(status: int) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status, request=request, json={"error": "transient"})
        return httpx.Response(200, request=request, json={"embeddings": [[0.0] * 2560]})

    adapter, client = make_adapter(handler)
    try:
        result = await adapter.embed_query("synthetic")
        assert len(result) == 2560
        assert calls == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_transient_connection_error_is_retried_and_sanitized() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("secret connection details", request=request)
        return httpx.Response(200, request=request, json={"embeddings": [[0.0] * 2560]})

    adapter, client = make_adapter(handler)
    try:
        result = await adapter.embed_query("synthetic")
        assert len(result) == 2560
        assert calls == 3
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_exhausted_connection_retries_return_sanitized_error() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("secret input and vector details", request=request)

    adapter, client = make_adapter(handler)
    try:
        with pytest.raises(OllamaEmbeddingError) as exc_info:
            await adapter.embed_query("synthetic")
        assert exc_info.value.code == "OLLAMA_UNAVAILABLE"
        assert calls == 3
        assert "secret" not in str(exc_info.value).lower()
        assert "synthetic" not in str(exc_info.value).lower()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_timeout_is_sanitized_and_invalid_dimensions_rejected() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("network timeout", request=request)

    adapter, client = make_adapter(handler)
    try:
        with pytest.raises(OllamaEmbeddingError) as exc_info:
            await adapter.embed_query("x")
        assert exc_info.value.code == "OLLAMA_TIMEOUT"
    finally:
        await client.aclose()
    for dimensions in (0, -1, 2048):
        with pytest.raises(ValueError):
            OllamaEmbeddingAdapter(
                base_url="https://ollama.test",
                api_token="secret",
                dimensions=dimensions,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url", ["http://ollama.test", "not-a-url", "ftp://ollama.test"]
)
async def test_insecure_or_invalid_endpoints_are_rejected(base_url: str) -> None:
    with pytest.raises(OllamaEmbeddingError) as exc_info:
        OllamaEmbeddingAdapter(base_url=base_url, api_token="secret")
    assert exc_info.value.code in {
        "INSECURE_OLLAMA_ENDPOINT",
        "OLLAMA_ENDPOINT_INVALID",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://host.docker.internal:11434",
    ],
)
async def test_local_http_endpoints_are_allowed(base_url: str) -> None:
    adapter = OllamaEmbeddingAdapter(base_url=base_url, api_token="secret")
    assert adapter.base_url == base_url


@pytest.mark.asyncio
async def test_http_408_is_retried_with_bounded_attempts() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(408, request=request)

    adapter, client = make_adapter(handler)
    try:
        with pytest.raises(OllamaEmbeddingError):
            await adapter.embed_query("x")
        assert calls == 3
    finally:
        await client.aclose()
