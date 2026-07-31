"""Unit tests for OllamaHealthAdapter with mocked HTTP client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from legal_ai.adapters.ollama.health import OllamaHealthAdapter
from legal_ai.domain.health import HealthStatus


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def adapter(mock_client: AsyncMock) -> OllamaHealthAdapter:
    return OllamaHealthAdapter(client=mock_client)


class TestCheck:
    @pytest.mark.anyio
    async def test_healthy(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "0.9.0"}
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await adapter.check()

        assert result.status == HealthStatus.OK
        assert result.latency_ms is not None
        mock_client.get.assert_awaited_once_with("/api/version")

    @pytest.mark.anyio
    async def test_invalid_json(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await adapter.check()

        assert result.status == HealthStatus.INVALID_RESPONSE
        assert result.error_code == "OLLAMA_INVALID_RESPONSE"

    @pytest.mark.anyio
    async def test_missing_version_field(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": []}
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await adapter.check()

        assert result.status == HealthStatus.INVALID_RESPONSE
        assert result.error_code == "OLLAMA_INVALID_RESPONSE"

    @pytest.mark.anyio
    async def test_empty_version_field(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "  "}
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await adapter.check()

        assert result.status == HealthStatus.INVALID_RESPONSE

    @pytest.mark.anyio
    async def test_http_401(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await adapter.check()

        assert result.status == HealthStatus.UNAUTHORIZED
        assert result.error_code == "OLLAMA_UNAUTHORIZED"

    @pytest.mark.anyio
    async def test_http_403(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await adapter.check()

        assert result.status == HealthStatus.FORBIDDEN
        assert result.error_code == "OLLAMA_FORBIDDEN"

    @pytest.mark.anyio
    async def test_http_404(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await adapter.check()

        assert result.status == HealthStatus.UNAVAILABLE
        assert result.error_code == "OLLAMA_ENDPOINT_NOT_FOUND"

    @pytest.mark.anyio
    async def test_http_429(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await adapter.check()

        assert result.status == HealthStatus.RATE_LIMITED
        assert result.error_code == "OLLAMA_RATE_LIMITED"

    @pytest.mark.anyio
    async def test_http_500(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await adapter.check()

        assert result.status == HealthStatus.UNAVAILABLE
        assert result.error_code == "OLLAMA_UNAVAILABLE"

    @pytest.mark.anyio
    async def test_http_418(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 418
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await adapter.check()

        assert result.status == HealthStatus.UNAVAILABLE
        assert "418" in result.message

    @pytest.mark.anyio
    async def test_connect_error(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await adapter.check()

        assert result.status == HealthStatus.UNAVAILABLE
        assert result.error_code == "OLLAMA_UNAVAILABLE"

    @pytest.mark.anyio
    async def test_timeout_exception(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        result = await adapter.check()

        assert result.status == HealthStatus.TIMEOUT
        assert result.error_code == "OLLAMA_TIMEOUT"

    @pytest.mark.anyio
    async def test_connect_timeout(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.get = AsyncMock(side_effect=httpx.ConnectTimeout("connect timeout"))

        result = await adapter.check()

        assert result.status == HealthStatus.TIMEOUT
        assert result.error_code == "OLLAMA_TIMEOUT"

    @pytest.mark.anyio
    async def test_read_timeout(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("read timeout"))

        result = await adapter.check()

        assert result.status == HealthStatus.TIMEOUT
        assert result.error_code == "OLLAMA_TIMEOUT"

    @pytest.mark.anyio
    async def test_generic_exception(
        self, adapter: OllamaHealthAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.get = AsyncMock(side_effect=RuntimeError("unexpected"))

        result = await adapter.check()

        assert result.status == HealthStatus.MISCONFIGURED
        assert result.error_code == "OLLAMA_MISCONFIGURED"
