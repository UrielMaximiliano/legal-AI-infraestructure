"""Ollama client for document generation."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


class OllamaError(Exception):
    """Base error for safe Ollama failures."""

    error_code = "GENERATION_FAILED"
    status_code = 502

    def __init__(self, message: str = "Ollama generation failed") -> None:
        super().__init__(message)


class OllamaUnavailableError(OllamaError):
    """Ollama service unavailable."""

    def __init__(self, message: str = "Ollama service unavailable") -> None:
        super().__init__(message)

    error_code = "OLLAMA_UNAVAILABLE"
    status_code = 503


class OllamaTimeoutError(OllamaError):
    """Ollama request timed out."""

    def __init__(self, message: str = "Ollama request timed out") -> None:
        super().__init__(message)

    error_code = "OLLAMA_TIMEOUT"
    status_code = 504


class GenerationFailedError(OllamaError):
    """Ollama responded but generation could not be completed."""

    error_code = "GENERATION_FAILED"
    status_code = 502


class OllamaResponseError(GenerationFailedError):
    """Ollama returned an invalid or unsuccessful response."""

    def __init__(self, message: str, upstream_status: int | None = None) -> None:
        self.upstream_status = upstream_status
        super().__init__(message)


@dataclass
class OllamaResponse:
    """Response from Ollama generation."""

    content: str
    model: str
    total_duration: int | None = None


class OllamaClient:
    """Client for Ollama API."""

    def __init__(self) -> None:
        self._base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self._model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self._timeout = int(os.getenv("OLLAMA_TIMEOUT", "30"))
        self._api_token = os.getenv("OLLAMA_API_TOKEN", "")

    @property
    def model(self) -> str:
        """Configured model name without exposing client internals."""
        return self._model

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        timeout: int | None = None,
    ) -> OllamaResponse:
        """Generate content using Ollama."""
        use_model = model or self._model
        use_timeout = timeout or self._timeout

        try:
            async with httpx.AsyncClient(timeout=use_timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/generate",
                    headers=(
                        {"Authorization": f"Bearer {self._api_token}"}
                        if self._api_token
                        else None
                    ),
                    json={
                        "model": use_model,
                        "prompt": prompt,
                        "stream": False,
                    },
                )

                if response.status_code == 401:
                    raise OllamaResponseError("Authentication failed", 401)
                if response.status_code == 403:
                    raise OllamaResponseError("Access forbidden", 403)
                if response.status_code == 404:
                    raise OllamaResponseError("Model not found", 404)
                if response.status_code == 429:
                    raise OllamaResponseError("Rate limited", 429)
                if response.status_code >= 500:
                    raise OllamaResponseError(
                        f"Ollama server error: {response.status_code}",
                        response.status_code,
                    )

                response.raise_for_status()

                data = response.json()
                content = data.get("response", "")
                if not content:
                    raise OllamaResponseError("Empty response from Ollama")

                return OllamaResponse(
                    content=content,
                    model=use_model,
                    total_duration=data.get("total_duration"),
                )

        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError() from exc
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError() from exc
        except OllamaError:
            raise
        except Exception as exc:
            raise OllamaUnavailableError() from exc
