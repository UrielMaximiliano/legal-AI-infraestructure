from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.main import app


@pytest.mark.contract
@pytest.mark.asyncio
async def test_rag_middleware_rejects_non_json_without_exposing_headers() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/rag/drafts/generate",
            content="not-json",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer test-token",
            },
        )
    assert response.status_code == 415
    assert response.headers["X-Request-ID"]
    assert "Authorization" not in response.text
    assert "should-never-be-logged" not in response.text


@pytest.mark.contract
@pytest.mark.asyncio
async def test_rag_middleware_rejects_oversized_body_before_route_work() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/rag/drafts/generate",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "999999999",
            },
        )
    assert response.status_code == 413
    assert response.json()["error_code"] == "RAG_REQUEST_TOO_LARGE"
