from __future__ import annotations

from typing import Any

import pytest

from legal_ai.cli import corpus_probe


class _Response:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _Client:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.requests: list[tuple[str, str]] = []

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, path: str) -> _Response:
        self.requests.append(("GET", path))
        return _Response(200, {"version": "0.9.0"})

    async def post(self, path: str, *, json: dict[str, Any]) -> _Response:
        self.requests.append(("POST", path))
        if path == "/api/show":
            return _Response(200, {"model_info": {"qwen3.embedding_length": 2560}})
        if path == corpus_probe.LEGACY_ENDPOINT:
            return _Response(200, {"embedding": [0.0] * corpus_probe.DIMENSIONS})
        return _Response(
            200,
            {"embeddings": [[0.0] * corpus_probe.DIMENSIONS for _ in json["input"]]},
        )


@pytest.mark.asyncio
async def test_probe_success_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(corpus_probe.httpx, "AsyncClient", _Client)
    result = await corpus_probe.probe("https://ollama.example", "secret-token")
    assert result["status"] == "passed"
    assert result["dimensions"] == 2560
    assert result["vector_count"] == 2
    assert result["query_vector_count"] == 1
    assert result["vectors_emitted"] is False
    assert "token" not in result


@pytest.mark.asyncio
async def test_probe_legacy_endpoint_is_sequential_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(corpus_probe.httpx, "AsyncClient", _Client)
    result = await corpus_probe.probe(
        "https://ollama.example", "secret-token", endpoint=corpus_probe.LEGACY_ENDPOINT
    )
    assert result["status"] == "passed"
    assert result["endpoint"] == corpus_probe.LEGACY_ENDPOINT
    assert result["transport_batch_supported"] is False
    assert result["application_batch_mode"] == "sequential"


@pytest.mark.asyncio
async def test_probe_rejects_insecure_or_missing_auth() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        await corpus_probe.probe("http://remote.example", "token")
    with pytest.raises(ValueError, match="BEARER"):
        await corpus_probe.probe("https://ollama.example", "")


def test_probe_vector_validation_rejects_bad_count_and_dimensions() -> None:
    with pytest.raises(ValueError, match="COUNT"):
        corpus_probe._validate_vectors({"embeddings": []}, 1)
    with pytest.raises(ValueError, match="VECTOR"):
        corpus_probe._validate_vectors(
            {"embeddings": [[0.0] * (corpus_probe.DIMENSIONS - 1)]}, 1
        )


def test_probe_main_sanitizes_failure(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("OLLAMA_EMBEDDING_BASE_URL", "http://remote.example")
    monkeypatch.setenv("OLLAMA_EMBEDDING_TOKEN", "secret-token")
    assert corpus_probe.main([]) == 2
    output = capsys.readouterr().out
    assert "G1_EXTERNAL_PROBE_FAILED" in output
    assert "secret-token" not in output
