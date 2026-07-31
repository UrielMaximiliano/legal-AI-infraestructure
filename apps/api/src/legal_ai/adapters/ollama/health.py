"""Adaptador de verificación de salud de Ollama."""

from __future__ import annotations

import time

import httpx

from legal_ai.domain.health import DependencyHealth, HealthStatus
from legal_ai.ports.ollama_health import OllamaHealthPort

# Mapeo de códigos HTTP a estados y códigos de error
_HTTP_ERROR_MAP: dict[int, tuple[HealthStatus, str]] = {
    401: (HealthStatus.UNAUTHORIZED, "OLLAMA_UNAUTHORIZED"),
    403: (HealthStatus.FORBIDDEN, "OLLAMA_FORBIDDEN"),
    404: (HealthStatus.UNAVAILABLE, "OLLAMA_ENDPOINT_NOT_FOUND"),
    429: (HealthStatus.RATE_LIMITED, "OLLAMA_RATE_LIMITED"),
}


class OllamaHealthAdapter(OllamaHealthPort):
    """Adaptador para verificación de salud de Ollama."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def check(self) -> DependencyHealth:
        """Verifica la conectividad con Ollama usando GET /api/version."""
        try:
            start = time.monotonic()
            response = await self._client.get("/api/version")
            latency_ms = (time.monotonic() - start) * 1000

            if response.status_code in _HTTP_ERROR_MAP:
                status, error_code = _HTTP_ERROR_MAP[response.status_code]
                return DependencyHealth(
                    status=status,
                    latency_ms=latency_ms,
                    error_code=error_code,
                )

            if response.status_code >= 500:
                return DependencyHealth(
                    status=HealthStatus.UNAVAILABLE,
                    latency_ms=latency_ms,
                    error_code="OLLAMA_UNAVAILABLE",
                    message="Ollama no accesible",
                )

            if response.status_code != 200:
                return DependencyHealth(
                    status=HealthStatus.UNAVAILABLE,
                    latency_ms=latency_ms,
                    error_code="OLLAMA_UNAVAILABLE",
                    message=f"HTTP {response.status_code}",
                )

            try:
                data = response.json()
            except Exception:
                return DependencyHealth(
                    status=HealthStatus.INVALID_RESPONSE,
                    latency_ms=latency_ms,
                    error_code="OLLAMA_INVALID_RESPONSE",
                    message="Respuesta no es JSON válido",
                )

            version = data.get("version")
            if not isinstance(version, str) or not version.strip():
                return DependencyHealth(
                    status=HealthStatus.INVALID_RESPONSE,
                    latency_ms=latency_ms,
                    error_code="OLLAMA_INVALID_RESPONSE",
                    message="Campo 'version' ausente o no es string no vacío",
                )

            return DependencyHealth(
                status=HealthStatus.OK,
                latency_ms=latency_ms,
            )

        except httpx.TimeoutException:
            return DependencyHealth(
                status=HealthStatus.TIMEOUT,
                error_code="OLLAMA_TIMEOUT",
                message="Timeout al conectar con Ollama",
            )
        except httpx.ConnectError:
            return DependencyHealth(
                status=HealthStatus.UNAVAILABLE,
                error_code="OLLAMA_UNAVAILABLE",
                message="Conexión rechazada",
            )
        except httpx.ConnectTimeout:
            return DependencyHealth(
                status=HealthStatus.TIMEOUT,
                error_code="OLLAMA_TIMEOUT",
                message="Timeout de conexión con Ollama",
            )
        except httpx.ReadTimeout:
            return DependencyHealth(
                status=HealthStatus.TIMEOUT,
                error_code="OLLAMA_TIMEOUT",
                message="Timeout de lectura con Ollama",
            )
        except Exception:
            return DependencyHealth(
                status=HealthStatus.MISCONFIGURED,
                error_code="OLLAMA_MISCONFIGURED",
                message="Error inesperado al conectar con Ollama",
            )
