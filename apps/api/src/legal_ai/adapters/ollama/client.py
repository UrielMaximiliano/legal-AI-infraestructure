"""Cliente HTTPX AsyncClient para Ollama con autenticación Bearer."""

from __future__ import annotations

import httpx

from legal_ai.config import settings


def create_ollama_client() -> httpx.AsyncClient:
    """Crea el cliente HTTPX AsyncClient para Ollama."""
    return httpx.AsyncClient(
        base_url=settings.ollama.base_url,
        timeout=httpx.Timeout(settings.ollama.timeout_seconds),
        headers={"Authorization": f"Bearer {settings.ollama.api_token}"},
    )
