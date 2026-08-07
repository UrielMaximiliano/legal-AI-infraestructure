from __future__ import annotations

from types import SimpleNamespace

import pytest

from legal_ai.api.routes import semantic_search as route
from legal_ai.schemas.semantic_search import (
    SemanticSearchRequest,
    SemanticSearchResponse,
)


@pytest.mark.asyncio
async def test_semantic_search_route_uses_request_correlation_and_safe_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class Service:
        async def search(self, payload, *, request_id: str):
            captured["request_id"] = request_id
            return SemanticSearchResponse(
                request_id=request_id,
                result_count=0,
                results=(),
            )

    monkeypatch.setattr(route, "_service", lambda: Service())
    response = await route.semantic_search(
        SemanticSearchRequest(
            query="designacion",
            document_type="decreto",
            document_subtype="designacion_transitoria",
            jurisdiction="nacion",
        ),
        SimpleNamespace(state=SimpleNamespace(request_id="request-id")),
    )
    assert captured == {"request_id": "request-id"}
    assert response.result_count == 0
    assert "raw_content" not in response.model_dump_json()
