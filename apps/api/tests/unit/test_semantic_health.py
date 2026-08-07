from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from legal_ai.adapters.ollama.health import OllamaHealthAdapter
from legal_ai.application.health_service import HealthService
from legal_ai.domain.health import DependencyHealth, HealthStatus
from tests.unit.test_health_service import FakeDatabaseHealth, FakeOllamaHealth


@pytest.mark.asyncio
async def test_health_reports_model_dimension_mismatch_without_details() -> None:
    client = AsyncMock(spec=httpx.AsyncClient)
    version = MagicMock(status_code=200)
    version.json.return_value = {"version": "0.9.0"}
    show = MagicMock(status_code=200)
    show.json.return_value = {"model_info": {"qwen3.embedding_length": 4096}}
    client.get.return_value = version
    client.post.return_value = show
    result = await OllamaHealthAdapter(
        client,
        expected_model="qwen3-embedding:4b-q4_K_M",
        expected_dimensions=2560,
    ).check()
    assert result.status == HealthStatus.MISCONFIGURED
    assert result.error_code == "OLLAMA_DIMENSIONS_INCOMPATIBLE"
    assert "4096" not in (result.message or "")


@pytest.mark.asyncio
async def test_health_provider_failure_is_sanitized() -> None:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = httpx.ConnectError("secret endpoint")
    result = await OllamaHealthAdapter(client).check()
    assert result.status == HealthStatus.UNAVAILABLE
    assert result.error_code == "OLLAMA_UNAVAILABLE"
    assert "secret" not in (result.message or "")


@pytest.mark.asyncio
async def test_semantic_capability_is_explicit_when_provider_is_down() -> None:
    service = HealthService(
        FakeDatabaseHealth(DependencyHealth(status=HealthStatus.OK)),
        FakeOllamaHealth(
            DependencyHealth(
                status=HealthStatus.UNAVAILABLE,
                error_code="OLLAMA_UNAVAILABLE",
            )
        ),
    )
    result = await service.check_all()
    assert result.semantic_retrieval is not None
    assert result.semantic_retrieval.status == HealthStatus.UNAVAILABLE
    assert result.semantic_retrieval.error_code == "OLLAMA_UNAVAILABLE"
