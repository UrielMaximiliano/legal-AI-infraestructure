from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.api.routes import rag as rag_routes
from legal_ai.application.rag_generation import RagGenerationError, RagGenerationOutcome
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus
from legal_ai.domain.rag import (
    RagGenerationRun,
    RagGenerationStatus,
    sha256_text,
)
from legal_ai.main import app


def _run() -> RagGenerationRun:
    return RagGenerationRun(
        id=uuid4(),
        case_file_id=uuid4(),
        template_id=uuid4(),
        request_hash=sha256_text("request"),
        query_hash=sha256_text("query"),
        idempotency_key_hash=sha256_text("key"),
        request_id="request-1",
    )


class _Runs:
    def __init__(self, run: RagGenerationRun | None) -> None:
        self.run = run

    async def get(self, run_id):
        return self.run if self.run is not None and self.run.id == run_id else None


class _Sources:
    async def list_by_run(self, run_id):
        del run_id
        return []


class _Uow:
    def __init__(self, run: RagGenerationRun | None) -> None:
        self.rag_runs = _Runs(run)
        self.rag_sources = _Sources()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback


def test_idempotency_header_is_strict() -> None:
    assert rag_routes.rag_idempotency_key("rag-key-00000001") == "rag-key-00000001"
    with pytest.raises(RagGenerationError):
        rag_routes.rag_idempotency_key("too-short")


@pytest.mark.asyncio
async def test_get_run_returns_sanitized_trace(monkeypatch) -> None:
    run = _run()
    monkeypatch.setattr(rag_routes, "UnitOfWork", lambda: _Uow(run))
    result = await rag_routes.get_rag_run(run.id)
    assert result.id == run.id
    assert result.sources == []
    assert result.request_id == "request-1"


@pytest.mark.asyncio
async def test_get_run_rejects_unknown_id(monkeypatch) -> None:
    monkeypatch.setattr(rag_routes, "UnitOfWork", lambda: _Uow(None))
    with pytest.raises(rag_routes.RagRunNotFoundError):
        await rag_routes.get_rag_run(uuid4())


@pytest.mark.asyncio
async def test_generate_endpoint_returns_pending_review_and_legacy_safe_fields(
    monkeypatch,
) -> None:
    template_id = uuid4()
    case_file_id = uuid4()
    draft_id = uuid4()
    run_id = uuid4()
    now = datetime.now(UTC)
    structured = _structured()
    run = RagGenerationRun(
        id=run_id,
        case_file_id=case_file_id,
        template_id=template_id,
        request_hash=sha256_text("request"),
        query_hash=sha256_text("query"),
        idempotency_key_hash=sha256_text("api-idempotency-key-0001"),
        status=RagGenerationStatus.SUCCEEDED,
        retrieved_count=1,
        selected_count=1,
        context_hash=sha256_text("context"),
        prompt_hash=sha256_text("prompt"),
        request_id="request-1",
        finished_at=now,
        updated_at=now,
    )
    draft = Draft(
        id=draft_id,
        template_id=template_id,
        case_file_id=case_file_id,
        title=structured.title,
        content=structured.render_for_review(),
        status=DraftStatus.GENERADO,
        version=1,
        generation_number=1,
        context_snapshot={"rag_run_id": str(run_id)},
        context_hash=sha256_text("context"),
        variables_used={"cargo": "Director"},
        request_id="request-1",
        created_at=now,
        updated_at=now,
    )
    outcome = RagGenerationOutcome(run, structured, draft, ())

    def _value(value, expected, result):
        return result if value == expected else None

    class _Repo:
        def __init__(self, expected, result) -> None:
            self.expected = expected
            self.result = result

        async def get_by_id(self, value):
            return _value(value, self.expected, self.result)

    class _Uow:
        def __init__(self) -> None:
            self.templates = _Repo(
                template_id,
                SimpleNamespace(is_active=True, variables=["cargo"])
            )
            self.case_files = _Repo(case_file_id, object())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

    class _Service:
        async def generate(self, *args, **kwargs):
            del args, kwargs
            return outcome

    monkeypatch.setattr(rag_routes, "UnitOfWork", _Uow)
    monkeypatch.setattr(rag_routes, "_build_service", lambda: (_Service(), object()))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/rag/drafts/generate",
            headers={"Idempotency-Key": "api-idempotency-key-0001"},
            json={
                "template_id": str(template_id),
                "case_file_id": str(case_file_id),
                "variables": {"cargo": "Director"},
            },
        )
    assert response.status_code == 201
    payload = response.json()
    assert payload["draft"]["status"] == "generado"
    assert payload["draft"]["id"] == str(draft_id)
    assert "vector" not in response.text.lower()


def _structured():
    from legal_ai.schemas.rag import RagStructuredDraft

    return RagStructuredDraft.model_validate(
        {
            "schema_version": 1,
            "title": "Generated decree",
            "visto": [{"text": "Visto", "citation_ids": ["SRC-001"]}],
            "considerandos": [
                {"text": "Considerando", "citation_ids": ["SRC-001"]}
            ],
            "dispositive_intro": "Por ello",
            "articles": [
                {"number": 1, "text": "Designar", "citation_ids": ["SRC-001"]}
            ],
            "closing": "Comunicar",
            "authority": "Autoridad",
            "signature": "Pendiente",
            "sources": [
                {
                    "citation_id": "SRC-001",
                    "external_id": "DOC-1",
                    "title": "Reviewed decree",
                    "publication_date": None,
                    "section_type": "CONSIDERANDO",
                }
            ],
            "warnings": ["NO VINCULANTE - REVISION HUMANA OBLIGATORIA"],
        }
    )
