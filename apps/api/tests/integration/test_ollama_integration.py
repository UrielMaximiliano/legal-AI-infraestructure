"""Ollama failure matrix with real PostgreSQL persistence."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import httpx
import pytest

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.api.exceptions import service_error_handler
from legal_ai.application.draft_service import DraftService
from legal_ai.application.ollama_client import (
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from tests.contract.helpers_003 import seed_case_and_template


class _HTTPClientContext:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def __aenter__(self) -> _HTTPClientContext:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> httpx.Response:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _response(status: int, payload: object) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("POST", "http://ollama/api/generate"),
    )


@pytest.mark.integration
async def test_ollama_success_creates_draft_and_completed_attempt(monkeypatch):
    fake = _HTTPClientContext(
        _response(200, {"response": "contenido", "model": "test"})
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)
    case_file_id, template_id = await seed_case_and_template()
    async with UnitOfWork() as uow:
        result = await DraftService(uow).generate_draft(
            str(template_id),
            str(case_file_id),
            idempotency_key=f"success-{uuid.uuid4().hex}",
        )
    assert result.content == "contenido"
    assert fake.calls[0]["headers"]["Authorization"].startswith("Bearer ")
    async with UnitOfWork() as uow:
        drafts, total = await uow.drafts.list_by_case_file(case_file_id, None, 0, 10)
        attempts = await uow.generation_attempts.list_by_case_file(case_file_id)
    assert total == 1 and drafts[0].content == "contenido"
    assert attempts[0].status.value == "completed"


@pytest.mark.integration
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
async def test_ollama_http_errors_persist_failed_attempt_without_draft(
    monkeypatch, status
):
    fake = _HTTPClientContext(_response(status, {"error": "secret upstream detail"}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)
    case_file_id, template_id = await seed_case_and_template()
    with pytest.raises(OllamaResponseError) as captured:
        async with UnitOfWork() as uow:
            await DraftService(uow).generate_draft(
                str(template_id),
                str(case_file_id),
                idempotency_key=f"http-{status}-{uuid.uuid4().hex}",
            )
    assert "secret upstream detail" not in str(captured.value)
    request = MagicMock()
    request.state.request_id = "ollama-http"
    handler_response = await service_error_handler(request, captured.value)
    assert handler_response.status_code == 502
    async with UnitOfWork() as uow:
        drafts, total = await uow.drafts.list_by_case_file(case_file_id, None, 0, 10)
        attempts = await uow.generation_attempts.list_by_case_file(case_file_id)
    assert total == 0 and not drafts
    assert attempts[0].status.value == "failed"


@pytest.mark.integration
async def test_ollama_timeout_maps_to_504_and_no_draft(monkeypatch):
    fake = _HTTPClientContext(httpx.ReadTimeout("secret-token timeout"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)
    case_file_id, template_id = await seed_case_and_template()
    with pytest.raises(OllamaTimeoutError) as captured:
        async with UnitOfWork() as uow:
            await DraftService(uow).generate_draft(
                str(template_id),
                str(case_file_id),
                idempotency_key=f"timeout-{uuid.uuid4().hex}",
            )
    assert "secret-token" not in str(captured.value)
    request = MagicMock()
    request.state.request_id = "ollama-timeout"
    response = await service_error_handler(request, captured.value)
    assert response.status_code == 504


@pytest.mark.integration
@pytest.mark.parametrize("payload", ["invalid-json", "empty"])
async def test_ollama_invalid_or_empty_response_is_safe(monkeypatch, payload):
    if payload == "invalid-json":
        response = httpx.Response(
            200,
            content=b"invalid-json",
            request=httpx.Request("POST", "http://ollama/api/generate"),
        )
    else:
        response = _response(200, {"response": ""})
    fake = _HTTPClientContext(response)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)
    case_file_id, template_id = await seed_case_and_template()
    with pytest.raises((OllamaUnavailableError, OllamaResponseError)) as captured:
        async with UnitOfWork() as uow:
            await DraftService(uow).generate_draft(
                str(template_id),
                str(case_file_id),
                idempotency_key=f"payload-{payload}-{uuid.uuid4().hex}",
            )
    message = str(captured.value)
    assert "invalid-json" not in message
    assert "prompt" not in message.lower()


@pytest.mark.integration
async def test_ollama_connection_reset_does_not_leak_credentials(monkeypatch):
    fake = _HTTPClientContext(httpx.ConnectError("OLLAMA_API_TOKEN=secret-token"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: fake)
    case_file_id, template_id = await seed_case_and_template()
    with pytest.raises(OllamaUnavailableError) as captured:
        async with UnitOfWork() as uow:
            await DraftService(uow).generate_draft(
                str(template_id),
                str(case_file_id),
                idempotency_key=f"connection-{uuid.uuid4().hex}",
            )
    message = str(captured.value)
    assert "secret-token" not in message
    assert "OLLAMA_API_TOKEN" not in message
    assert "Authorization" not in message
