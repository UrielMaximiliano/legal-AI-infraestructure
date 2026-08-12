"""Ollama /api/chat adapter for structured RAG generation."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

import httpx

from legal_ai.ports.structured_generation import StructuredGenerationError

logger = logging.getLogger("uvicorn.error")


class OllamaStructuredGenerationProvider:
    """Private, bounded, non-streaming Ollama chat client."""

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        model: str = "qwen3.6:35b",
        endpoint: str = "/api/chat",
        timeout_seconds: float = 300.0,
        max_retries: int = 1,
        context_window: int = 8_192,
        max_output_tokens: int = 3_072,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if model != "qwen3.6:35b" or endpoint != "/api/chat":
            raise ValueError("OLLAMA_GENERATION_CONTRACT_INVALID")
        if context_window < 4_096 or not 512 <= max_output_tokens < context_window:
            raise ValueError("OLLAMA_GENERATION_TOKEN_BUDGET_INVALID")
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OLLAMA_GENERATION_ENDPOINT_INVALID")
        if parsed.scheme == "http" and parsed.hostname.lower() not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "host.docker.internal",
        }:
            raise ValueError("INSECURE_OLLAMA_ENDPOINT")
        if not api_token and parsed.hostname.lower() not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "host.docker.internal",
        }:
            raise ValueError("OLLAMA_GENERATION_TOKEN_REQUIRED")
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout_seconds
        self.max_retries = max(0, min(max_retries, 2))
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout
        )
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.post(
                        self.endpoint, json=payload, headers=self._headers()
                    )
                except httpx.TimeoutException as exc:
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.1 * (2**attempt))
                        continue
                    raise StructuredGenerationError(
                        "OLLAMA_TIMEOUT", retryable=True
                    ) from exc
                except httpx.HTTPError as exc:
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.1 * (2**attempt))
                        continue
                    raise StructuredGenerationError(
                        "OLLAMA_UNAVAILABLE", retryable=True
                    ) from exc
                if response.status_code in {408, 429} or response.status_code >= 500:
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.1 * (2**attempt))
                        continue
                    raise StructuredGenerationError(
                        "OLLAMA_UNAVAILABLE", retryable=True
                    )
                if response.status_code in {401, 403}:
                    raise StructuredGenerationError("OLLAMA_AUTHENTICATION_FAILED")
                if response.status_code >= 400:
                    raise StructuredGenerationError("OLLAMA_REQUEST_INVALID")
                try:
                    body = response.json()
                except ValueError as exc:
                    raise StructuredGenerationError("OLLAMA_RESPONSE_INVALID") from exc
                if not isinstance(body, dict):
                    raise StructuredGenerationError("OLLAMA_RESPONSE_INVALID")
                return body
            raise StructuredGenerationError("OLLAMA_UNAVAILABLE", retryable=True)
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _parse_content(content: object) -> Mapping[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise StructuredGenerationError("OLLAMA_RESPONSE_INVALID")
        clean = content.strip()
        if clean.startswith("```") and clean.endswith("```"):
            clean = clean[3:-3].strip()
            if clean.startswith("json"):
                clean = clean[4:].lstrip()
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError as exc:
            logger.warning(
                "ollama_structured_json_invalid chars=%s line=%s column=%s "
                "position=%s open_braces=%s close_braces=%s",
                len(clean),
                exc.lineno,
                exc.colno,
                exc.pos,
                clean.count("{"),
                clean.count("}"),
            )
            raise StructuredGenerationError("RAG_OUTPUT_INVALID") from exc
        if not isinstance(parsed, dict):
            raise StructuredGenerationError("RAG_OUTPUT_INVALID")
        return parsed

    @staticmethod
    def _schema_for_context(
        schema: Mapping[str, Any], context: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        """Restrict opaque citation fields to the sources actually retrieved."""

        allowed = sorted(
            {
                citation_id
                for source in context
                if isinstance((citation_id := source.get("citation_id")), str)
                and citation_id.startswith("SRC-")
            }
        )
        result = deepcopy(dict(schema))
        if not allowed:
            return result

        optional_source_values = {
            field: sorted(
                {
                    value if isinstance(value, str) else None
                    for source in context
                    for value in (source.get(field),)
                },
                key=lambda value: value or "",
            )
            for field in ("publication_date", "source_url")
        }

        def constrain(value: object, field: str | None = None) -> None:
            if isinstance(value, dict):
                if value.get("pattern") == "^SRC-[0-9][0-9][0-9]$":
                    value["enum"] = allowed
                if field in optional_source_values:
                    value["enum"] = optional_source_values[field]
                for child_field, child in value.items():
                    constrain(child, child_field)
            elif isinstance(value, list):
                for child in value:
                    constrain(child)

        constrain(result)
        return result

    async def generate_structured(
        self,
        *,
        system_message: str,
        user_message: str,
        schema: Mapping[str, Any],
        temperature: float = 0.1,
        context: Sequence[Mapping[str, Any]] = (),
    ) -> Mapping[str, Any]:
        if not system_message.strip() or not user_message.strip():
            raise ValueError("OLLAMA_GENERATION_INPUT_EMPTY")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "think": False,
            "format": self._schema_for_context(schema, context),
            "options": {
                "temperature": temperature,
                "num_ctx": self.context_window,
                "num_predict": self.max_output_tokens,
            },
        }
        body = await self._request(payload)
        message = body.get("message")
        if not isinstance(message, dict):
            raise StructuredGenerationError("OLLAMA_RESPONSE_INVALID")
        content = message.get("content")
        logger.info(
            "ollama_structured_response done_reason=%s prompt_tokens=%s "
            "output_tokens=%s content_chars=%s",
            body.get("done_reason"),
            body.get("prompt_eval_count"),
            body.get("eval_count"),
            len(content) if isinstance(content, str) else 0,
        )
        return self._parse_content(content)

    async def health_check(self) -> Mapping[str, Any]:
        return {"status": "ready", "model": self.model}
