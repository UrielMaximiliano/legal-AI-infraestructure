"""Real Ollama/RAG acceptance; every test requires explicit operator opt-in."""

from __future__ import annotations

import json
import math
import os
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.corpus_models import (
    CorpusChunkModel,
    CorpusDocumentModel,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.models import (
    DocumentDraftModel,
    DocumentReviewModel,
    ReviewEventModel,
)
from legal_ai.adapters.database.rag_models import (
    RagGenerationRunModel,
    RagRetrievedSourceModel,
    RagStructuredDraftModel,
)
from legal_ai.adapters.ollama.structured_generation import (
    OllamaStructuredGenerationProvider,
)
from legal_ai.adapters.ollama_embedding import OllamaEmbeddingAdapter
from legal_ai.api.routes.rag import close_rag_coordinator
from legal_ai.application.rag_query import RagQueryBuilder
from legal_ai.config import settings
from legal_ai.main import app
from legal_ai.schemas.rag import RagStructuredDraft, rag_schema

from .rag_postgres_support import run_alembic
from .test_rag_postgres_e2e import _CaseSeed, _cleanup, _seed

pytestmark = pytest.mark.integration


def _require_opt_in() -> None:
    if os.environ.get("RAG_REAL_ACCEPTANCE") != "1":
        pytest.skip("Set RAG_REAL_ACCEPTANCE=1 to run real Ollama acceptance")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _assert_authorized_https(base_url: str, token: str) -> None:
    parsed = urlsplit(base_url)
    assert parsed.scheme == "https"
    assert parsed.username is None and parsed.password is None
    assert token


def _assert_no_sensitive_payload(value: object) -> None:
    forbidden_keys = {
        "authorization",
        "embedding",
        "embeddings",
        "normalized_content",
        "prompt",
        "query",
        "raw_content",
        "storage_path",
        "token",
        "vector",
        "vectors",
    }
    if isinstance(value, dict):
        assert not forbidden_keys.intersection(key.lower() for key in value)
        for child in value.values():
            _assert_no_sensitive_payload(child)
    elif isinstance(value, list):
        assert not (
            len(value) > 128
            and all(isinstance(item, (int, float)) for item in value)
        )
        for child in value:
            _assert_no_sensitive_payload(child)


@pytest.mark.asyncio
async def test_real_ollama_embed_contract_opt_in() -> None:
    """T069: authorized batch embeddings are exact, finite and stable."""

    _require_opt_in()
    token = settings.ollama.api_token
    _assert_authorized_https(settings.ollama.base_url, token)
    texts = (
        "Antecedente juridico sintetico para designacion transitoria.",
        "Borrador sintetico sujeto a revision humana obligatoria.",
    )
    request = {
        "model": "qwen3-embedding:4b-q4_K_M",
        "input": list(texts),
        "dimensions": 2560,
    }
    async with httpx.AsyncClient(
        base_url=settings.ollama.base_url,
        timeout=settings.corpus.embedding_timeout_seconds,
    ) as client:
        first = await client.post("/api/embed", headers=_headers(token), json=request)
        second = await client.post("/api/embed", headers=_headers(token), json=request)
        anonymous = await client.post("/api/embed", json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert anonymous.status_code in {401, 403, 404}
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload.get("model") == "qwen3-embedding:4b-q4_K_M"
    vectors = first_payload.get("embeddings")
    repeated = second_payload.get("embeddings")
    assert isinstance(vectors, list) and len(vectors) == len(texts)
    assert isinstance(repeated, list) and len(repeated) == len(texts)
    for vector, repeated_vector in zip(vectors, repeated, strict=True):
        assert isinstance(vector, list) and len(vector) == 2560
        assert isinstance(repeated_vector, list) and len(repeated_vector) == 2560
        assert all(
            isinstance(item, (int, float)) and math.isfinite(item)
            for item in vector
        )
        assert vector == pytest.approx(repeated_vector, rel=1e-7, abs=1e-8)


@pytest.mark.asyncio
async def test_real_ollama_chat_schema_contract_opt_in() -> None:
    """T070: the contractual model returns a fully valid closed-schema draft."""

    _require_opt_in()
    token = settings.rag.generation_token or settings.ollama.api_token
    _assert_authorized_https(settings.rag.generation_base_url, token)
    request = {
        "model": "qwen3.6:35b",
        "stream": False,
        "format": OllamaStructuredGenerationProvider._schema_for_context(
            rag_schema(),
            (
                {
                    "citation_id": "SRC-001",
                    "publication_date": None,
                    "source_url": None,
                },
            ),
        ),
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return only valid JSON matching the schema. Use only SRC-001. "
                    "Include exactly this warning: BORRADOR NO VINCULANTE; "
                    "REVISION HUMANA OBLIGATORIA. The source is SRC-001, external_id "
                    "TEST-001, title Antecedente sintetico, publication_date null, "
                    "section_type CONSIDERANDO and source_url null."
                ),
            },
            {"role": "user", "content": "Create one synthetic legal draft."},
        ],
    }
    async with httpx.AsyncClient(
        base_url=settings.rag.generation_base_url,
        timeout=settings.rag.generation_timeout_seconds,
    ) as client:
        anonymous = await client.post("/api/chat", json=request)
        assert anonymous.status_code in {401, 403}
        response = await client.post(
            "/api/chat", headers=_headers(token), json=request
        )

    response.raise_for_status()
    payload = response.json()
    assert payload.get("model") == "qwen3.6:35b"
    content = payload.get("message", {}).get("content")
    assert isinstance(content, str) and content
    draft = RagStructuredDraft.model_validate(json.loads(content))
    assert draft.schema_version == 1
    assert draft.citation_ids == ("SRC-001",)
    assert settings.rag.generation_max_retries == 1


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_real_rag_http_smoke_is_idempotent_audited_and_review_only() -> None:
    """T071: local HTTP RAG with isolated PostgreSQL and real Ollama."""

    _require_opt_in()
    run_alembic("upgrade", "007")
    engine = create_engine()
    seed: _CaseSeed | None = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            seed = await _seed(session, with_case=True)
            await session.commit()

        query = RagQueryBuilder().build(
            variables={
                "case_file_id": str(seed.case_file_id),
                "template_id": str(seed.template_id),
                "cargo": "Director",
            }
        )
        embedding = await OllamaEmbeddingAdapter(
            base_url=settings.ollama.base_url,
            api_token=settings.ollama.api_token,
            model=settings.embedding.model,
            dimensions=settings.embedding.dimensions,
            timeout_seconds=settings.corpus.embedding_timeout_seconds,
            endpoint=settings.ollama.endpoint,
        ).embed_query(query.text)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                update(CorpusChunkModel)
                .where(CorpusChunkModel.id == seed.corpus.chunk_id)
                .values(embedding=embedding)
            )
            await session.commit()

        body = {
            "template_id": str(seed.template_id),
            "case_file_id": str(seed.case_file_id),
            "variables": {"cargo": "Director"},
        }
        idempotency_key = "rag-real-" + uuid4().hex
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://rag-isolated.test",
            timeout=settings.rag.generation_timeout_seconds,
        ) as client:
            first = await client.post(
                "/api/v1/rag/drafts/generate",
                headers={"Idempotency-Key": idempotency_key},
                json=body,
            )
            second = await client.post(
                "/api/v1/rag/drafts/generate",
                headers={"Idempotency-Key": idempotency_key},
                json=body,
            )

        assert first.status_code == 201, first.json()
        assert second.status_code == 201, second.json()
        first_payload = first.json()
        second_payload = second.json()
        _assert_no_sensitive_payload(first_payload)
        assert first_payload["rag_run_id"] == second_payload["rag_run_id"]
        assert first_payload["draft"]["id"] == second_payload["draft"]["id"]
        assert first_payload["draft"]["status"] == "PENDING_REVIEW"
        assert first_payload["retrieval"]["selected_count"] > 0

        run_id = UUID(first_payload["rag_run_id"])
        draft_id = UUID(first_payload["draft"]["id"])
        response_citations = {
            source["citation_id"]
            for source in first_payload["structured_draft"]["sources"]
        }
        async with AsyncSession(engine, expire_on_commit=False) as session:
            run = await session.get(RagGenerationRunModel, run_id)
            draft = await session.get(DocumentDraftModel, draft_id)
            review = await session.scalar(
                select(DocumentReviewModel).where(
                    DocumentReviewModel.draft_id == draft_id
                )
            )
            event = await session.scalar(
                select(ReviewEventModel).where(
                    ReviewEventModel.run_id == run_id,
                    ReviewEventModel.event_type == "REVIEW_OPENED",
                )
            )
            structured = await session.scalar(
                select(RagStructuredDraftModel).where(
                    RagStructuredDraftModel.run_id == run_id
                )
            )
            sources = (
                await session.scalars(
                    select(RagRetrievedSourceModel).where(
                        RagRetrievedSourceModel.run_id == run_id,
                        RagRetrievedSourceModel.disposition == "SELECTED",
                    )
                )
            ).all()
            run_count = await session.scalar(
                select(func.count(RagGenerationRunModel.id)).where(
                    RagGenerationRunModel.case_file_id == seed.case_file_id
                )
            )
            holdout_count = await session.scalar(
                select(func.count(CorpusDocumentModel.id))
                .join(
                    RagRetrievedSourceModel,
                    RagRetrievedSourceModel.document_id == CorpusDocumentModel.id,
                )
                .where(
                    RagRetrievedSourceModel.run_id == run_id,
                    CorpusDocumentModel.metadata_json["evaluation_split"].astext
                    == "HOLDOUT_10",
                )
            )

        assert run is not None and run.status == "SUCCEEDED"
        assert draft is not None and draft.status == "en_revision"
        assert review is not None and review.status == "OPEN"
        assert event is not None and event.draft_id == draft_id
        assert structured is not None and structured.draft_id == draft_id
        assert run_count == 1
        assert holdout_count == 0
        assert sources
        assert {source.citation_id for source in sources} == response_citations
        assert all(source.document_id == seed.corpus.document_id for source in sources)
        assert all(source.chunk_id == seed.corpus.chunk_id for source in sources)
    finally:
        await close_rag_coordinator()
        if seed is not None:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await _cleanup(session, seed)
                await session.commit()
        await engine.dispose()
