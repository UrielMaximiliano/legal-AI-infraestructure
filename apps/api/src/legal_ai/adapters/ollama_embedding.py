"""Ollama embedding adapter with strict, sanitized contract validation.

The native ``/api/embed`` endpoint accepts a batch.  Some externally exposed
Ollama proxies publish only the legacy ``/api/embeddings`` endpoint, which
accepts one prompt at a time.  The endpoint is therefore explicit
configuration, never an implicit fallback.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

import httpx

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


class OllamaEmbeddingError(RuntimeError):
    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


EMBEDDING_ENDPOINT_BATCH = "/api/embed"
EMBEDDING_ENDPOINT_LEGACY = "/api/embeddings"
ALLOWED_EMBEDDING_ENDPOINTS = frozenset(
    {EMBEDDING_ENDPOINT_BATCH, EMBEDDING_ENDPOINT_LEGACY}
)


class OllamaEmbeddingAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        model: str = EMBEDDING_MODEL,
        dimensions: int = EMBEDDING_DIMENSIONS,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        endpoint: str = EMBEDDING_ENDPOINT_BATCH,
        context_length: int = 2048,
    ) -> None:
        if dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"EMBEDDING_DIMENSIONS debe ser {EMBEDDING_DIMENSIONS}"
            )
        if not model or not api_token:
            raise ValueError("OLLAMA_EMBEDDING_CONFIGURATION_INVALID")
        if context_length <= 0 or context_length > 32768:
            raise ValueError("OLLAMA_EMBEDDING_CONTEXT_LENGTH_INVALID")
        self._validate_endpoint(base_url)
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout_seconds
        self._client = client
        self.max_retries = max(0, max_retries)
        if endpoint not in ALLOWED_EMBEDDING_ENDPOINTS:
            raise ValueError("OLLAMA_EMBEDDING_ENDPOINT_INVALID")
        self.endpoint = endpoint
        self.context_length = context_length

    @staticmethod
    def _validate_endpoint(base_url: str) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise OllamaEmbeddingError("OLLAMA_ENDPOINT_INVALID")
        if parsed.scheme == "http" and parsed.hostname.lower() not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "host.docker.internal",
        }:
            raise OllamaEmbeddingError("INSECURE_OLLAMA_ENDPOINT")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.api_token,
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout
        )
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.request(
                        method, path, json=payload, headers=self._headers()
                    )
                except httpx.TimeoutException as exc:
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.1 * (2**attempt))
                        continue
                    raise OllamaEmbeddingError("OLLAMA_TIMEOUT") from exc
                except httpx.HTTPError as exc:
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.1 * (2**attempt))
                        continue
                    raise OllamaEmbeddingError("OLLAMA_UNAVAILABLE") from exc
                if response.status_code in {408, 429} or response.status_code >= 500:
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.1 * (2**attempt))
                        continue
                    raise OllamaEmbeddingError(
                        "OLLAMA_RATE_LIMITED"
                        if response.status_code == 429
                        else "OLLAMA_PROVIDER_ERROR",
                        status_code=response.status_code,
                    )
                if response.status_code in {401, 403}:
                    raise OllamaEmbeddingError(
                        "OLLAMA_AUTHENTICATION_FAILED", status_code=response.status_code
                    )
                if response.status_code >= 400:
                    raise OllamaEmbeddingError(
                        "OLLAMA_REQUEST_INVALID", status_code=response.status_code
                    )
                try:
                    body = response.json()
                except ValueError as exc:
                    raise OllamaEmbeddingError("OLLAMA_RESPONSE_INVALID") from exc
                if not isinstance(body, dict):
                    raise OllamaEmbeddingError("OLLAMA_RESPONSE_INVALID")
                return body
            raise OllamaEmbeddingError("OLLAMA_PROVIDER_ERROR")
        finally:
            if owns_client:
                await client.aclose()

    def _validate(self, embeddings: Any, expected_count: int) -> list[list[float]]:
        if not isinstance(embeddings, list) or len(embeddings) != expected_count:
            raise OllamaEmbeddingError("OLLAMA_EMBEDDING_COUNT_MISMATCH")
        result: list[list[float]] = []
        for vector in embeddings:
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise OllamaEmbeddingError("OLLAMA_EMBEDDING_DIMENSIONS_MISMATCH")
            if not vector or not all(
                isinstance(value, (int, float)) and math.isfinite(value)
                for value in vector
            ):
                raise OllamaEmbeddingError("OLLAMA_EMBEDDING_VECTOR_INVALID")
            result.append([float(value) for value in vector])
        return result

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if (
            isinstance(texts, str)
            or not texts
            or any(not isinstance(text, str) or not text for text in texts)
        ):
            raise OllamaEmbeddingError("OLLAMA_INPUT_EMPTY")
        if self.endpoint == EMBEDDING_ENDPOINT_BATCH:
            body = await self._request(
                "POST",
                self.endpoint,
                {
                    "model": self.model,
                    "input": list(texts),
                    "dimensions": self.dimensions,
                    "options": {"num_ctx": self.context_length},
                },
            )
            return self._validate(body.get("embeddings"), len(texts))

        # The legacy endpoint has no batch input.  Keep application-level
        # ordering deterministic and validate every response before returning
        # any vectors to the caller.
        vectors: list[list[float]] = []
        for text in texts:
            body = await self._request(
                "POST", self.endpoint, {"model": self.model, "prompt": text}
            )
            vectors.extend(self._validate([body.get("embedding")], 1))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]

    async def health_check(self) -> dict[str, Any]:
        version = await self._request("GET", "/api/version")
        model = await self._request("POST", "/api/show", {"name": self.model})
        return {
            "version": version.get("version"),
            "model": self.model,
            "show": {"details": model.get("details")},
        }
