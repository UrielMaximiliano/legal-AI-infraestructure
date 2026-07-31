"""Pruebas del adaptador Ollama con mocks."""

from __future__ import annotations

import httpx
import pytest

from legal_ai.adapters.ollama.health import OllamaHealthAdapter
from legal_ai.domain.health import HealthStatus


def _make_adapter(response: httpx.Response) -> OllamaHealthAdapter:
    """Crea un adaptador con un mock del cliente."""
    client = httpx.AsyncClient(
        base_url="http://test",
        headers={"Authorization": "Bearer test-token"},
    )

    async def mock_get(url: str, **kwargs: object) -> httpx.Response:
        return response

    client.get = mock_get  # type: ignore[method-assign]
    return OllamaHealthAdapter(client)


@pytest.mark.unit
class TestOllamaHealthAdapter:
    """Pruebas para OllamaHealthAdapter."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        """Verifica respuesta exitosa."""
        response = httpx.Response(
            200,
            json={"version": "0.1.0"},
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        assert result.status == HealthStatus.OK
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_invalid_json(self) -> None:
        """Verifica manejo de JSON inválido."""
        response = httpx.Response(
            200,
            text="not json",
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        assert result.status == HealthStatus.INVALID_RESPONSE
        assert result.error_code == "OLLAMA_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_missing_version_field(self) -> None:
        """Verifica manejo de campo version ausente."""
        response = httpx.Response(
            200,
            json={"other": "value"},
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        assert result.status == HealthStatus.INVALID_RESPONSE
        assert result.error_code == "OLLAMA_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_empty_version_string(self) -> None:
        """Verifica manejo de version string vacío."""
        response = httpx.Response(
            200,
            json={"version": ""},
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        assert result.status == HealthStatus.INVALID_RESPONSE

    @pytest.mark.asyncio
    async def test_http_401(self) -> None:
        """Verifica manejo de HTTP 401."""
        response = httpx.Response(
            401,
            json={"error": "unauthorized"},
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        assert result.status == HealthStatus.UNAUTHORIZED
        assert result.error_code == "OLLAMA_UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_http_403(self) -> None:
        """Verifica manejo de HTTP 403."""
        response = httpx.Response(
            403,
            json={"error": "forbidden"},
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        assert result.status == HealthStatus.FORBIDDEN
        assert result.error_code == "OLLAMA_FORBIDDEN"

    @pytest.mark.asyncio
    async def test_http_404(self) -> None:
        """Verifica manejo de HTTP 404."""
        response = httpx.Response(
            404,
            json={"error": "not found"},
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        assert result.status == HealthStatus.UNAVAILABLE
        assert result.error_code == "OLLAMA_ENDPOINT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_http_429(self) -> None:
        """Verifica manejo de HTTP 429."""
        response = httpx.Response(
            429,
            json={"error": "rate limited"},
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        assert result.status == HealthStatus.RATE_LIMITED
        assert result.error_code == "OLLAMA_RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_http_502(self) -> None:
        """Verifica manejo de HTTP 502."""
        response = httpx.Response(
            502,
            text="Bad Gateway",
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        assert result.status == HealthStatus.UNAVAILABLE
        assert result.error_code == "OLLAMA_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_http_504(self) -> None:
        """Verifica manejo de HTTP 504."""
        response = httpx.Response(
            504,
            text="Gateway Timeout",
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        assert result.status == HealthStatus.UNAVAILABLE
        assert result.error_code == "OLLAMA_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        """Verifica manejo de error de conexión."""
        client = httpx.AsyncClient(
            base_url="http://invalid-host:99999",
            headers={"Authorization": "Bearer test-token"},
        )
        adapter = OllamaHealthAdapter(client)
        result = await adapter.check()
        assert result.status in (HealthStatus.UNAVAILABLE, HealthStatus.TIMEOUT)

    @pytest.mark.asyncio
    async def test_token_not_exposed(self) -> None:
        """Verifica que el token no se expone en errores."""
        response = httpx.Response(
            401,
            json={"error": "unauthorized"},
            request=httpx.Request("GET", "http://test/api/version"),
        )
        adapter = _make_adapter(response)
        result = await adapter.check()
        # El token no debe aparecer en el mensaje de error
        assert result.message is None or "test-token" not in (result.message or "")
