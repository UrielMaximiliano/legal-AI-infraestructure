from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from starlette.responses import Response

from legal_ai.adapters.database.rag_models import (
    RagRetrievedSourceModel,
    RagStructuredDraftModel,
)
from legal_ai.adapters.database.rag_repositories import (
    SQLAlchemyRagGenerationRunRepository,
    SQLAlchemyRagRetrievedSourceRepository,
    SQLAlchemyRagStructuredDraftRepository,
)
from legal_ai.adapters.generation.fake_structured_generation import (
    FakeStructuredGenerationProvider,
)
from legal_ai.adapters.ollama.structured_generation import (
    OllamaStructuredGenerationProvider,
)
from legal_ai.application.inference_coordinator import InferenceCoordinator
from legal_ai.application.rag_context import ContextAssembler
from legal_ai.application.rag_evaluation import (
    RagEvaluationManifestError,
    evaluate_manifest,
    load_manifest,
)
from legal_ai.application.rag_generation import (
    InMemoryRagAuditStore,
    RagGenerationError,
    RagGenerationOutcome,
    RagGenerationService,
    SQLAlchemyRagAuditStore,
)
from legal_ai.application.rag_query import RagQueryBuilder
from legal_ai.application.rag_retrieval import RagRetrievalResult
from legal_ai.domain.case_file import CaseFile
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import CaseType, DraftStatus, TemplateDocumentType
from legal_ai.domain.rag import (
    RagGenerationRun,
    RagGenerationStatus,
    RagRetrievedSource,
    RagSourceDisposition,
    canonical_json,
    citation_id,
    estimate_tokens,
    sanitize_error_code,
    sha256_json,
    sha256_text,
    validate_hash,
)
from legal_ai.domain.template import Template
from legal_ai.observability.rag import record_rag_event, sanitize_rag_event
from legal_ai.ports.structured_generation import StructuredGenerationError
from legal_ai.schemas.rag import RagDraftGenerationRequest, rag_schema


def _run(**changes: object) -> RagGenerationRun:
    value = RagGenerationRun(
        id=uuid4(),
        case_file_id=uuid4(),
        template_id=uuid4(),
        request_hash=sha256_text("request"),
        query_hash=sha256_text("query"),
        idempotency_key_hash=sha256_text("key"),
    )
    return replace(value, **changes)


def _source(
    *,
    rank: int = 1,
    disposition: RagSourceDisposition = RagSourceDisposition.SELECTED,
    context_rank: int | None = 1,
    excerpt: str = "Reviewed evidence",
) -> RagRetrievedSource:
    return RagRetrievedSource(
        document_id=uuid4(),
        chunk_id=uuid4(),
        external_id="DOC-1",
        title="Reviewed decree",
        publication_date="2025-01-01",
        section_type="CONSIDERANDO",
        generation=1,
        similarity_score=0.9,
        retrieval_rank=rank,
        citation_id=citation_id(rank),
        excerpt=excerpt,
        disposition=disposition,
        context_rank=context_rank,
        content_hash=sha256_text(excerpt),
    )


def _request() -> RagDraftGenerationRequest:
    return RagDraftGenerationRequest(
        template_id=uuid4(), case_file_id=uuid4(), variables={"cargo": "Director"}
    )


def _structured_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "title": "Draft",
        "visto": [{"text": "Visto", "citation_ids": ["SRC-001"]}],
        "considerandos": [{"text": "Considerando", "citation_ids": ["SRC-001"]}],
        "dispositive_intro": "Por ello",
        "articles": [{"number": 1, "text": "Designar", "citation_ids": []}],
        "closing": "Comunicar",
        "authority": "Autoridad",
        "signature": "Pendiente",
        "sources": [
            {
                "citation_id": "SRC-001",
                "external_id": "DOC-1",
                "title": "Reviewed decree",
                "publication_date": "2025-01-01",
                "section_type": "CONSIDERANDO",
            }
        ],
        "warnings": ["NO VINCULANTE - REVISION HUMANA OBLIGATORIA"],
    }


class _Retrieval:
    async def retrieve(self, query: str, **_: object) -> RagRetrievalResult:
        source = _source()
        context = ContextAssembler().assemble((source,))
        return RagRetrievalResult(
            query_hash=sha256_text(query),
            sources=context.sources,
            context=context,
            duration_ms=2,
            embedding_model="qwen3-embedding:4b-q4_K_M",
            embedding_dimensions=2560,
        )


class _Session:
    def __init__(self, result: object | None = None) -> None:
        self.added: list[object] = []
        self.result = result

    def add(self, value: object) -> None:
        self.added.append(value)

    def add_all(self, values: list[object]) -> None:
        self.added.extend(values)

    async def add_none(self) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def execute(self, statement: object) -> object:
        del statement
        return self.result


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def first(self) -> object | None:
        return self.values[0] if self.values else None

    def all(self) -> list[object]:
        return self.values


class _Result:
    def __init__(self, values: list[object]) -> None:
        self._scalars = _Scalars(values)

    def scalars(self) -> _Scalars:
        return self._scalars


def test_rag_domain_validation_helpers_and_invariants() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert sha256_json({"a": 1}) == sha256_json({"a": 1})
    digest = sha256_text("ok")
    assert validate_hash(digest) == digest
    with pytest.raises(ValueError, match="BAD_HASH"):
        validate_hash("bad", "BAD_HASH")
    assert sanitize_error_code(" rag_output_invalid ") == "RAG_OUTPUT_INVALID"
    assert sanitize_error_code("OLLAMA_TIMEOUT") == "OLLAMA_TIMEOUT"
    assert sanitize_error_code("not allowed") == "RAG_INTERNAL_ERROR"
    assert sanitize_error_code(4) == "RAG_INTERNAL_ERROR"
    assert estimate_tokens("") == 1
    with pytest.raises(ValueError, match="RAG_CITATION_ID_INVALID"):
        citation_id(0)
    with pytest.raises(ValueError, match="RAG_CITATION_ID_INVALID"):
        citation_id(1000)
    for kwargs, code in [
        ({"external_id": "", "title": "Title"}, "RAG_SOURCE_METADATA_INVALID"),
        ({"similarity_score": 2.0}, "RAG_SOURCE_SCORE_INVALID"),
        ({"retrieval_rank": 0}, "RAG_SOURCE_RANK_INVALID"),
        ({"generation": 0}, "RAG_SOURCE_GENERATION_INVALID"),
        ({"content_hash": "bad"}, "RAG_SOURCE_CONTENT_HASH_INVALID"),
        ({"context_rank": None}, "RAG_SOURCE_CONTEXT_RANK_REQUIRED"),
    ]:
        base = {
            "document_id": uuid4(),
            "chunk_id": uuid4(),
            "external_id": "DOC-1",
            "title": "Title",
            "publication_date": None,
            "section_type": "VISTO",
            "generation": 1,
            "similarity_score": 0.5,
            "retrieval_rank": 1,
            "citation_id": "SRC-001",
            "excerpt": "evidence",
            "context_rank": 1,
        }
        base.update(kwargs)
        with pytest.raises(ValueError, match=code):
            RagRetrievedSource(**base)


@pytest.mark.asyncio
async def test_route_builds_contract_bound_service() -> None:
    from legal_ai.api.routes import rag as rag_routes

    rag_routes.settings.ollama.base_url = "http://localhost:11434"
    rag_routes.settings.ollama.api_token = "test-token"
    service, coordinator = rag_routes._build_service()
    second_service, second_coordinator = rag_routes._build_service()
    assert isinstance(service, RagGenerationService)
    assert service._generation_model == "qwen3.6:35b"
    assert isinstance(second_service, RagGenerationService)
    assert coordinator is second_coordinator
    await rag_routes.close_rag_coordinator()


def test_query_builder_and_observability_are_allowlisted() -> None:
    query = RagQueryBuilder().build(
        case_file={"case_number": "42", "embedding": "secret", "bad-key": "skip"},
        variables={"cargo": "Director", "count": 3},
    )
    assert "case_number: 42" in query.text
    assert "embedding" not in query.text
    with pytest.raises(ValueError, match="RAG_ORGANIZATION_INVALID"):
        RagQueryBuilder().build(variables={"cargo": "Director"}, organization="token")
    with pytest.raises(ValueError, match="RAG_LANGUAGE_INVALID"):
        RagQueryBuilder().build(variables={"cargo": "Director"}, language="x")
    values = sanitize_rag_event(
        {"run_id": "run", "prompt": "secret", "object": object(), "count": 1}
    )
    assert values == {"run_id": "run"}
    record_rag_event("generation", values)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"request_hash": "bad"}, "RAG_REQUEST_HASH_INVALID"),
        ({"query_hash": "bad"}, "RAG_QUERY_HASH_INVALID"),
        ({"idempotency_key_hash": "bad"}, "RAG_IDEMPOTENCY_HASH_INVALID"),
        ({"embedding_model": "other"}, "RAG_EMBEDDING_MODEL_INVALID"),
        ({"embedding_dimensions": 3}, "RAG_EMBEDDING_DIMENSIONS_INVALID"),
        ({"generation_model": "other"}, "RAG_GENERATION_MODEL_INVALID"),
        ({"top_k": 2}, "RAG_RETRIEVAL_LIMIT_INVALID"),
        ({"candidate_pool_size": 2}, "RAG_RETRIEVAL_LIMIT_INVALID"),
        ({"minimum_score": 2.0}, "RAG_SCORE_INVALID"),
        ({"retrieved_count": -1}, "RAG_SOURCE_COUNT_INVALID"),
        ({"selected_count": 2}, "RAG_SOURCE_COUNT_INVALID"),
        ({"schema_repair_count": 2}, "RAG_SCHEMA_REPAIR_COUNT_INVALID"),
    ],
)
def test_rag_generation_run_rejects_invalid_values(
    changes: dict[str, object], code: str
) -> None:
    with pytest.raises(ValueError, match=code):
        _run(**changes)


@pytest.mark.asyncio
async def test_in_memory_store_clears_failed_pending_and_detects_mismatch() -> None:
    store = InMemoryRagAuditStore()
    key_hash = sha256_text("idempotency")
    request_hash = sha256_text("request")
    assert await store.reserve(key_hash, request_hash) is None
    with pytest.raises(RagGenerationError) as mismatch:
        await store.reserve(key_hash, sha256_text("other"))
    assert mismatch.value.code == "RAG_IDEMPOTENCY_KEY_MISMATCH"
    failed = _run(
        idempotency_key_hash=key_hash,
        request_hash=request_hash,
        status=RagGenerationStatus.FAILED,
    )
    await store.update(failed)
    assert await store.reserve(key_hash, request_hash) is None
    await store.create(failed)
    await store.create_sources(failed.id, (_source(),))


@pytest.mark.asyncio
async def test_generation_rejects_bad_inputs_and_provider_citation() -> None:
    service = RagGenerationService(
        retrieval=_Retrieval(), provider=FakeStructuredGenerationProvider()
    )
    with pytest.raises(RagGenerationError) as key_error:
        await service.generate(_request(), idempotency_key="short", request_id="req")
    assert key_error.value.code == "RAG_INVALID_REQUEST"
    with pytest.raises(RagGenerationError) as request_error:
        await service.generate(
            _request(), idempotency_key="valid-key-0000001", request_id=""
        )
    assert request_error.value.code == "RAG_INVALID_REQUEST"
    with pytest.raises(ValueError):
        RagGenerationService(
            retrieval=_Retrieval(),
            provider=FakeStructuredGenerationProvider(),
            generation_model="other",
        )
    with pytest.raises(ValueError):
        RagGenerationService(
            retrieval=_Retrieval(),
            provider=FakeStructuredGenerationProvider(),
            embedding_dimensions=3,
        )


class _UnknownCitationProvider:
    async def generate_structured(self, **_: object) -> dict[str, object]:
        return {
            "schema_version": 1,
            "title": "Draft",
            "visto": [{"text": "Visto", "citation_ids": ["SRC-999"]}],
            "considerandos": [{"text": "Considerando", "citation_ids": ["SRC-001"]}],
            "dispositive_intro": "Por ello",
            "articles": [{"number": 1, "text": "Designar", "citation_ids": []}],
            "closing": "Comunicar",
            "authority": "Autoridad",
            "signature": "Pendiente",
            "sources": [
                {
                    "citation_id": "SRC-001",
                    "external_id": "DOC-1",
                    "title": "Reviewed decree",
                    "publication_date": "2025-01-01",
                    "section_type": "CONSIDERANDO",
                }
            ],
            "warnings": ["NO VINCULANTE - REVISION HUMANA OBLIGATORIA"],
        }


@pytest.mark.asyncio
async def test_generation_provider_error_and_coordinator_paths() -> None:
    class _Provider:
        async def generate_structured(self, **_: object) -> dict[str, object]:
            raise StructuredGenerationError("OLLAMA_TIMEOUT", retryable=True)

    service = RagGenerationService(
        retrieval=_Retrieval(), provider=_Provider(), schema_repair_attempts=0
    )
    with pytest.raises(RagGenerationError) as error:
        await service.generate(
            _request(), idempotency_key="provider-key-00001", request_id="req"
        )
    assert error.value.code == "OLLAMA_TIMEOUT"
    coordinator = InferenceCoordinator(max_queue_size=2, wait_timeout=1)
    coordinated = RagGenerationService(
        retrieval=_Retrieval(),
        provider=FakeStructuredGenerationProvider(),
        inference_coordinator=coordinator,
    )
    try:
        outcome = await coordinated.generate(
            _request(), idempotency_key="coord-key-000001", request_id="req"
        )
    finally:
        await coordinator.close()
    assert outcome.draft is not None


@pytest.mark.asyncio
async def test_generation_rejects_unknown_citations_and_audit_create_errors() -> None:
    service = RagGenerationService(
        retrieval=_Retrieval(),
        provider=_UnknownCitationProvider(),
        schema_repair_attempts=0,
    )
    with pytest.raises(RagGenerationError) as citation_error:
        await service.generate(
            _request(), idempotency_key="citation-key-0001", request_id="req"
        )
    assert citation_error.value.code == "RAG_OUTPUT_INVALID"

    class _CreateErrorAudit(InMemoryRagAuditStore):
        async def create(self, run: RagGenerationRun) -> None:
            del run
            raise RuntimeError("audit unavailable")

    service = RagGenerationService(
        retrieval=_Retrieval(),
        provider=FakeStructuredGenerationProvider(),
        audit=_CreateErrorAudit(),
    )
    with pytest.raises(RagGenerationError) as audit_error:
        await service.generate(
            _request(), idempotency_key="create-error-key", request_id="req"
        )
    assert audit_error.value.code == "RAG_AUDIT_UNAVAILABLE"

    cached = RagGenerationOutcome(
        _run(status=RagGenerationStatus.SUCCEEDED), None, None, ()
    )

    class _RaceAudit(InMemoryRagAuditStore):
        def __init__(self) -> None:
            super().__init__()
            self.reserve_calls = 0

        async def reserve(self, key_hash: str, request_hash: str):
            del key_hash, request_hash
            self.reserve_calls += 1
            return cached if self.reserve_calls == 2 else None

        async def create(self, run: RagGenerationRun) -> None:
            del run
            raise RagGenerationError("RAG_GENERATION_IN_PROGRESS")

    race = _RaceAudit()
    service = RagGenerationService(
        retrieval=_Retrieval(), provider=FakeStructuredGenerationProvider(), audit=race
    )
    result = await service.generate(
        _request(), idempotency_key="race-key-0000001", request_id="req"
    )
    assert result is cached


@pytest.mark.asyncio
async def test_generation_fails_closed_when_retrieval_or_sources_fail() -> None:
    class _BrokenRetrieval:
        async def retrieve(self, query: str, **_: object) -> RagRetrievalResult:
            del query
            raise RuntimeError("search unavailable")

    store = InMemoryRagAuditStore()
    service = RagGenerationService(
        retrieval=_BrokenRetrieval(),
        provider=FakeStructuredGenerationProvider(),
        audit=store,
    )
    with pytest.raises(RagGenerationError) as retrieval_error:
        await service.generate(
            _request(), idempotency_key="retrieval-key-0001", request_id="req"
        )
    assert retrieval_error.value.code == "SEMANTIC_SEARCH_AUDIT_UNAVAILABLE"
    assert next(iter(store.runs.values())).status is RagGenerationStatus.FAILED

    class _BrokenSources(InMemoryRagAuditStore):
        async def create_sources(self, run_id: object, sources: object) -> None:
            del run_id, sources
            raise RuntimeError("source audit unavailable")

    service = RagGenerationService(
        retrieval=_Retrieval(),
        provider=FakeStructuredGenerationProvider(),
        audit=_BrokenSources(),
    )
    with pytest.raises(RagGenerationError) as source_error:
        await service.generate(
            _request(), idempotency_key="source-key-000001", request_id="req"
        )
    assert source_error.value.code == "SEMANTIC_SEARCH_AUDIT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_sql_audit_store_rejects_incomplete_outcome() -> None:
    store = SQLAlchemyRagAuditStore()
    outcome = RagGenerationOutcome(_run(), None, None, ())
    with pytest.raises(RagGenerationError) as error:
        await store.save_outcome("key", outcome)
    assert error.value.code == "RAG_AUDIT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_sql_audit_store_round_trips_cached_outcome_and_writes() -> None:
    draft = Draft(
        id=uuid4(),
        template_id=uuid4(),
        case_file_id=uuid4(),
        title="Draft",
        content="content",
        status=DraftStatus.GENERADO,
        version=1,
        generation_number=1,
        context_snapshot={},
        context_hash=sha256_text("context"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    existing = _run(
        status=RagGenerationStatus.SUCCEEDED,
        draft_id=draft.id,
        retrieved_count=1,
        selected_count=1,
        context_hash=sha256_text("context"),
        prompt_hash=sha256_text("prompt"),
        finished_at=datetime.now(UTC),
    )
    structured_model = type("Structured", (), {"content_json": _structured_payload()})()

    class _Runs:
        def __init__(self) -> None:
            self.created: list[object] = []
            self.updated: list[object] = []

        async def find_by_idempotency_hash(self, key: str):
            del key
            return existing

        async def create(self, value: object) -> None:
            self.created.append(value)

        async def update(self, value: object) -> None:
            self.updated.append(value)

    class _Drafts:
        async def get_by_id(self, value):
            return draft if draft is not None and value == draft.id else None

        async def create(self, value: object) -> None:
            del value

    class _Structured:
        async def get_by_run(self, value):
            return structured_model if value == existing.id else None

        async def create(self, **kwargs: object) -> None:
            del kwargs

    class _Sources:
        async def create_many(self, run_id: object, sources: object) -> None:
            del run_id, sources

    class _Reviews:
        async def create(self, value: object) -> object:
            return value

    class _ReviewEvents:
        async def create(self, value: object) -> object:
            return value

    class _Uow:
        def __init__(self) -> None:
            self.rag_runs = _Runs()
            self.drafts = _Drafts()
            self.rag_structured_drafts = _Structured()
            self.rag_sources = _Sources()
            self.reviews = _Reviews()
            self.review_events = _ReviewEvents()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

    store = SQLAlchemyRagAuditStore(_Uow)
    cached = await store.reserve("key", existing.request_hash)
    assert cached is not None and cached.draft is draft
    with pytest.raises(RagGenerationError) as mismatch:
        await store.reserve("key", sha256_text("other"))
    assert mismatch.value.code == "RAG_IDEMPOTENCY_KEY_MISMATCH"

    saved_existing = existing
    existing = replace(existing, draft_id=None)
    with pytest.raises(RagGenerationError) as no_draft:
        await SQLAlchemyRagAuditStore(_Uow).reserve("key", existing.request_hash)
    assert no_draft.value.code == "RAG_AUDIT_UNAVAILABLE"
    existing = saved_existing
    saved_draft = draft
    draft = None  # type: ignore[assignment]
    with pytest.raises(RagGenerationError) as missing_draft:
        await SQLAlchemyRagAuditStore(_Uow).reserve("key", existing.request_hash)
    assert missing_draft.value.code == "RAG_AUDIT_UNAVAILABLE"
    draft = saved_draft
    saved_structured = structured_model
    structured_model = None
    with pytest.raises(RagGenerationError) as missing_structured:
        await SQLAlchemyRagAuditStore(_Uow).reserve("key", existing.request_hash)
    assert missing_structured.value.code == "RAG_AUDIT_UNAVAILABLE"
    structured_model = saved_structured

    pending = replace(existing, status=RagGenerationStatus.RETRIEVING)
    class _PendingUow(_Uow):
        def __init__(self) -> None:
            super().__init__()
            self.rag_runs.find_by_idempotency_hash = (  # type: ignore[method-assign]
                lambda key: _return_value(pending, key)
            )

    async def pending_value(value: object, key: object) -> object:
        del key
        return value

    async def _return_value(value: object, key: object) -> object:
        return await pending_value(value, key)

    with pytest.raises(RagGenerationError) as in_progress:
        await SQLAlchemyRagAuditStore(_PendingUow).reserve("key", pending.request_hash)
    assert in_progress.value.code == "RAG_GENERATION_IN_PROGRESS"

    class _IntegrityRuns(_Runs):
        async def create(self, value: object) -> None:
            del value
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    class _IntegrityUow(_Uow):
        def __init__(self) -> None:
            super().__init__()
            self.rag_runs = _IntegrityRuns()

    with pytest.raises(RagGenerationError) as duplicate:
        await SQLAlchemyRagAuditStore(_IntegrityUow).create(existing)
    assert duplicate.value.code == "RAG_GENERATION_IN_PROGRESS"

    await store.create(existing)
    await store.update(existing)
    await store.create_sources(existing.id, (_source(),))
    await store.save_outcome(
        "key", RagGenerationOutcome(existing, cached.structured_draft, draft, ())
    )


def _ollama_provider(
    handler, *, max_retries: int = 0, base_url: str = "https://ollama.test"
) -> tuple[OllamaStructuredGenerationProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=base_url
    )
    return (
        OllamaStructuredGenerationProvider(
            base_url=base_url,
            api_token="token" if base_url.startswith("https") else "",
            client=client,
            max_retries=max_retries,
        ),
        client,
    )


@pytest.mark.asyncio
async def test_ollama_adapter_rejects_configuration_and_input() -> None:
    with pytest.raises(ValueError):
        OllamaStructuredGenerationProvider(
            base_url="https://ollama.test", api_token="token", model="other"
        )
    with pytest.raises(ValueError):
        OllamaStructuredGenerationProvider(
            base_url="https://ollama.test", api_token="token", endpoint="/bad"
        )
    with pytest.raises(ValueError):
        OllamaStructuredGenerationProvider(
            base_url="ftp://ollama.test", api_token="token"
        )
    with pytest.raises(ValueError):
        OllamaStructuredGenerationProvider(
            base_url="https://user:pass@ollama.test", api_token="token"
        )
    with pytest.raises(ValueError):
        OllamaStructuredGenerationProvider(
            base_url="http://remote.example", api_token=""
        )
    provider = OllamaStructuredGenerationProvider(
        base_url="http://localhost:11434", api_token=""
    )
    assert provider.health_check is not None
    with pytest.raises(ValueError, match="OLLAMA_GENERATION_INPUT_EMPTY"):
        await provider.generate_structured(
            system_message="", user_message="user", schema={}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "OLLAMA_REQUEST_INVALID"),
        (403, "OLLAMA_AUTHENTICATION_FAILED"),
        (500, "OLLAMA_UNAVAILABLE"),
    ],
)
async def test_ollama_adapter_maps_http_errors(status: int, code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, json={"error": "hidden"})

    provider, client = _ollama_provider(handler)
    try:
        with pytest.raises(StructuredGenerationError) as error:
            await provider.generate_structured(
                system_message="system", user_message="user", schema={}
            )
    finally:
        await client.aclose()
    assert error.value.code == code


@pytest.mark.asyncio
async def test_ollama_adapter_constrains_citations_to_retrieved_context() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "{}"}})

    provider, client = _ollama_provider(handler)
    try:
        await provider.generate_structured(
            system_message="system",
            user_message="user",
            schema=rag_schema(),
            context=({"citation_id": "SRC-007"},),
        )
    finally:
        await client.aclose()

    def citation_enums(value: object) -> list[list[str]]:
        found: list[list[str]] = []
        if isinstance(value, dict):
            if value.get("pattern") == "^SRC-[0-9][0-9][0-9]$":
                found.append(value["enum"])
            for child in value.values():
                found.extend(citation_enums(child))
        elif isinstance(value, list):
            for child in value:
                found.extend(citation_enums(child))
        return found

    assert citation_enums(captured["format"]) == [["SRC-007"]] * 4


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"message": []}, {"message": {"content": ""}}])
async def test_ollama_adapter_rejects_invalid_responses(body: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=body)

    provider, client = _ollama_provider(handler)
    try:
        with pytest.raises(StructuredGenerationError):
            await provider.generate_structured(
                system_message="system", user_message="user", schema={}
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_ollama_adapter_translates_transport_and_timeout_errors() -> None:
    def transport_error(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectError("unavailable")

    provider, client = _ollama_provider(transport_error, max_retries=0)
    try:
        with pytest.raises(StructuredGenerationError) as error:
            await provider.generate_structured(
                system_message="system", user_message="user", schema={}
            )
    finally:
        await client.aclose()
    assert error.value.code == "OLLAMA_UNAVAILABLE"

    def timeout_error(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ReadTimeout("timeout")

    provider, client = _ollama_provider(timeout_error, max_retries=0)
    try:
        with pytest.raises(StructuredGenerationError) as error:
            await provider.generate_structured(
                system_message="system", user_message="user", schema={}
            )
    finally:
        await client.aclose()
    assert error.value.code == "OLLAMA_TIMEOUT"


@pytest.mark.asyncio
async def test_rag_repositories_read_and_update_models() -> None:
    run_model = SQLAlchemyRagGenerationRunRepository._to_model(_run())
    session = _Session(_Result([run_model]))
    repo = SQLAlchemyRagGenerationRunRepository(session)
    assert (await repo.get(run_model.id)) is not None
    assert (await repo.find_by_idempotency_hash("key")) is not None
    await repo.update(_run(id=run_model.id))
    await repo.create(_run())
    assert session.added

    source_model = RagRetrievedSourceModel(
        run_id=run_model.id,
        document_id=uuid4(),
        chunk_id=uuid4(),
        citation_id="SRC-001",
        retrieval_rank=1,
        context_rank=1,
        similarity_score=0.9,
        disposition="SELECTED",
        section_type="VISTO",
        generation=1,
        content_hash=sha256_text("evidence"),
    )
    source_repo = SQLAlchemyRagRetrievedSourceRepository(
        _Session(_Result([source_model]))
    )
    assert len(await source_repo.list_by_run(run_model.id)) == 1

    structured_model = RagStructuredDraftModel(
        run_id=run_model.id,
        draft_id=uuid4(),
        schema_version=1,
        content_json={"schema_version": 1},
        content_hash=sha256_text("structured"),
        citation_count=1,
        warning_count=1,
    )
    structured_repo = SQLAlchemyRagStructuredDraftRepository(
        _Session(_Result([structured_model]))
    )
    assert await structured_repo.get_by_run(run_model.id) is structured_model


@pytest.mark.asyncio
async def test_route_generation_success_and_validation(monkeypatch) -> None:
    from legal_ai.api.routes import rag as rag_routes

    template_id = uuid4()
    case_id = uuid4()
    template = Template(
        id=template_id,
        name="Template",
        document_type=TemplateDocumentType.RESOLUCION,
        version=1,
        body_template="{cargo}",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        variables=["cargo"],
    )
    case = CaseFile(
        id=case_id,
        case_number="1",
        employee_id=uuid4(),
        title="Case",
        case_type=CaseType.DESIGNACION,
    )

    class _Templates:
        async def get_by_id(self, value):
            return template if value == template_id else None

    class _Cases:
        async def get_by_id(self, value):
            return case if value == case_id else None

    class _Uow:
        templates = _Templates()
        case_files = _Cases()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

    class _Coordinator:
        async def close(self) -> None:
            return None

    service = RagGenerationService(
        retrieval=_Retrieval(), provider=FakeStructuredGenerationProvider()
    )
    monkeypatch.setattr(rag_routes, "UnitOfWork", _Uow)
    monkeypatch.setattr(rag_routes, "_build_service", lambda: (service, _Coordinator()))
    request = Request({"type": "http", "method": "POST", "path": "/"})
    request.state.request_id = "req-route"
    result = await rag_routes.generate_rag_draft(
        request,
        Response(),
        _request().model_copy(
            update={"template_id": template_id, "case_file_id": case_id}
        ),
        "route-key-000001",
    )
    assert result.draft.status == "generado"

    missing = _request().model_copy(
        update={"template_id": template_id, "case_file_id": case_id, "variables": {}}
    )
    with pytest.raises(RagGenerationError) as missing_error:
        await rag_routes.generate_rag_draft(
            request, Response(), missing, "route-key-000002"
        )
    assert missing_error.value.code == "MISSING_REQUIRED_VARIABLES"


def test_holdout_evaluation_validates_and_computes_fake_metrics(tmp_path: Path) -> None:
    pdf = tmp_path / "case.pdf"
    pdf.write_bytes(b"holdout")
    digest = sha256_text("holdout")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "dataset_version": "v1",
                "split": "HOLDOUT_10",
                "source": "external",
                "cases": [
                    {
                        "case_id": "H-1",
                        "relative_path": "case.pdf",
                        "sha256": digest,
                        "external_id": "HOLDOUT-1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded, root = load_manifest(str(manifest), limit=1)
    assert loaded.cases[0].case_id == "H-1"
    assert root == tmp_path.resolve()
    result = evaluate_manifest(str(manifest), execute=True, provider="fake")
    assert result["metrics"]["schema_valid_rate"] == 1.0
    with pytest.raises(RagEvaluationManifestError, match="RAG_LIMIT_INVALID"):
        evaluate_manifest(str(manifest), limit=0)
    with pytest.raises(RagEvaluationManifestError, match="RAG_PROVIDER_INVALID"):
        evaluate_manifest(str(manifest), provider="bad")
    with pytest.raises(
        RagEvaluationManifestError, match="RAG_EXTERNAL_PROVIDER_NOT_CONFIGURED"
    ):
        evaluate_manifest(str(manifest), execute=True, provider="ollama")
