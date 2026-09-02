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


def test_allowed_template_variables_include_optional_body_placeholders() -> None:
    template = SimpleNamespace(
        variables=["fecha"],
        body_template="Fecha: {{fecha}}; beneficiario: {{beneficiario}}",
    )

    allowed = rag_routes._allowed_template_variables(template)

    assert allowed == {"fecha", "beneficiario"}
    assert "inventada" not in allowed


def test_concept_rewrite_validation_rejects_facts_not_present_in_input() -> None:
    assert rag_routes._validate_concept_rewrite(
        "mantenimiento de computadoras",
        "servicio de mantenimiento integral de equipos informáticos",
    ) == "servicio de mantenimiento integral de equipos informáticos"
    assert rag_routes._validate_concept_rewrite(
        "mantenimiento de computadoras",
        "Se establece el gasto en el Programa 20 mediante Decreto 798/2026.",
    ) is None
    assert rag_routes._validate_concept_rewrite(
        "mantenimiento de computadoras",
        "adquisición de vehículos oficiales",
    ) is None


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


@pytest.mark.asyncio
async def test_rewrite_endpoint_returns_validated_text_and_reviewed_sources(
    monkeypatch,
) -> None:
    template_id = uuid4()
    captured: dict[str, object] = {}
    source = SimpleNamespace(
        disposition=SimpleNamespace(value="SELECTED"),
        citation_id="SRC-001",
        external_id="DEC-1",
        title="Decreto revisado",
        excerpt="Texto jurídico revisado.",
        publication_date=None,
        section_type="CONSIDERANDO",
        source_url=None,
    )

    class _Retrieval:
        async def retrieve(self, query, **kwargs):
            captured["query"] = query
            captured["filters"] = kwargs["filters"]
            return SimpleNamespace(
                sources=(source,),
                embedding_model="qwen3-embedding:0.6b",
                embedding_dimensions=1024,
            )

    class _Provider:
        async def generate_structured(self, **kwargs):
            captured["system_message"] = kwargs["system_message"]
            return {
                "text": "prestación del servicio de mantenimiento integral",
                "citation_ids": ["SRC-001"],
            }

    class _Coordinator:
        async def execute(self, priority, operation, *, timeout):
            del priority
            captured["timeout"] = timeout
            return await operation()

    service = SimpleNamespace(
        _retrieval=_Retrieval(),
        _provider=_Provider(),
        _generation_context_length=16_384,
        _generation_model="qwen3.6:35b",
    )

    async def _template_context(*args):
        assert args == (template_id,)
        return object()

    monkeypatch.setattr(rag_routes, "_validate_template_context", _template_context)
    monkeypatch.setattr(
        rag_routes,
        "_query_context",
        lambda *args: {
            "document_type": "decreto",
            "document_subtype": None,
            "jurisdiction": "nacion",
            "target_document_type": "disposicion",
        },
    )
    monkeypatch.setattr(rag_routes, "_build_service", lambda: (service, _Coordinator()))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/rag/text/rewrite",
            json={
                "template_id": str(template_id),
                "text": "mantenimiento de computadoras",
                "retrieval": {"top_k": 8, "minimum_score": 0},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "prestación del servicio de mantenimiento integral"
    assert payload["citation_ids"] == ["SRC-001"]
    assert payload["retrieval"]["embedding_dimensions"] == 1024
    assert captured["query"] == "mantenimiento de computadoras"
    assert "Concepto de una Disposición por Fondo Permanente" in str(
        captured["system_message"]
    )
    assert payload["generation"]["prompt_version"].endswith(
        ":text-rewrite:disposicion"
    )
    assert captured["filters"] == {
        "document_type": "decreto",
        "jurisdiction": "nacion",
        "review_status": "REVIEWED",
        "evaluation_split": "INDEX_90",
    }
    assert captured["timeout"] == 300


def test_rewrite_prompt_is_specific_to_nota_inicio() -> None:
    prompt = rag_routes._rewrite_prompt("nota_inicio")

    assert "Razón de la actuación de una Nota de Inicio" in prompt
    assert "motivo concreto por el cual se inician las actuaciones" in prompt
    assert "comienza exactamente con 'proceso de'" in prompt
    assert "Concepto de una Disposición" not in prompt


def test_nota_rewrite_is_grammatical_after_fixed_article() -> None:
    assert rag_routes._normalize_rewrite_for_target(
        "incorporación de becarios para tareas administrativas",
        "nota_inicio",
    ) == "proceso de incorporación de becarios para tareas administrativas"
    assert rag_routes._normalize_rewrite_for_target(
        "servicio de mantenimiento de computadoras",
        "nota_inicio",
    ) == "servicio de mantenimiento de computadoras"
    assert rag_routes._normalize_rewrite_for_target(
        "incorporación de becarios",
        "disposicion",
    ) == "incorporación de becarios"


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
