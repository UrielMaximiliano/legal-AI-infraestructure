"""Readiness exposes an empty reviewed corpus without probing model content."""

from __future__ import annotations

import pytest

from legal_ai.api.routes import health


@pytest.mark.integration
@pytest.mark.asyncio
async def test_readiness_is_not_ready_when_corpus_query_is_unavailable(
    monkeypatch,
) -> None:
    class _BrokenUow:
        async def __aenter__(self):
            raise RuntimeError("isolated database unavailable")

        async def __aexit__(self, *args: object) -> None:
            del args

    monkeypatch.setattr(health, "UnitOfWork", _BrokenUow)
    health.settings.ollama.base_url = "http://test-host:11434"
    health.settings.ollama.api_token = "test-token"
    readiness = await health._rag_generation_readiness()
    assert readiness.status == "unavailable"
    assert readiness.error_code == "RAG_CORPUS_UNAVAILABLE"
