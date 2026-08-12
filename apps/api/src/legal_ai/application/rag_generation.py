"""Auditable orchestration of retrieval, structured generation and Draft creation."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.inference_coordinator import InferenceCoordinator
from legal_ai.application.rag_prompt import RagPrompt, RagPromptBuilder
from legal_ai.application.rag_query import RagQueryBuilder
from legal_ai.application.rag_retrieval import RagRetrievalService
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus, ReviewStatus
from legal_ai.domain.errors import DomainError
from legal_ai.domain.rag import (
    RagGenerationRun,
    RagGenerationStatus,
    RagSourceDisposition,
    sanitize_error_code,
    sha256_json,
    sha256_text,
)
from legal_ai.domain.review import DocumentReview
from legal_ai.domain.review_event import ReviewEvent
from legal_ai.ports.embedding import InferencePriority
from legal_ai.ports.structured_generation import (
    StructuredGenerationError,
    StructuredGenerationProvider,
)
from legal_ai.schemas.rag import (
    RagDraftGenerationRequest,
    RagStructuredDraft,
    rag_generation_schema,
)

# Uvicorn owns the process logging configuration in production.  Using its
# error logger keeps the validation diagnostics visible without logging the
# model output, prompt, retrieved content, or credentials.
logger = logging.getLogger("uvicorn.error")
_REVIEW_WARNING = "BORRADOR NO VINCULANTE SUJETO A REVISION HUMANA"


class RagGenerationError(DomainError):
    """Stable failure for the API layer; never carries upstream content."""

    def __init__(self, code: str) -> None:
        self.code = sanitize_error_code(code)
        self.status_code = {
            "RAG_INVALID_REQUEST": 400,
            "MISSING_REQUIRED_VARIABLES": 422,
            "RAG_IDEMPOTENCY_KEY_MISMATCH": 409,
            "RAG_GENERATION_IN_PROGRESS": 409,
            "RAG_INSUFFICIENT_EVIDENCE": 422,
            "RAG_OUTPUT_INVALID": 422,
            "OLLAMA_TIMEOUT": 504,
        }.get(self.code, 503)
        message = {
            "MISSING_REQUIRED_VARIABLES": (
                "Faltan variables requeridas por la plantilla."
            ),
            "RAG_INSUFFICIENT_EVIDENCE": (
                "No hay antecedentes revisados suficientes para generar el borrador."
            ),
            "RAG_OUTPUT_INVALID": "La salida estructurada no pudo validarse.",
            "RAG_GENERATION_IN_PROGRESS": (
                "La generación solicitada ya está en progreso."
            ),
        }.get(self.code, "La generación RAG no pudo completarse.")
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RagGenerationOutcome:
    run: RagGenerationRun
    structured_draft: RagStructuredDraft | None
    draft: Draft | None
    sources: tuple[Any, ...]


class RagAuditStore(Protocol):
    async def reserve(
        self, key_hash: str, request_hash: str
    ) -> RagGenerationOutcome | None: ...

    async def create(self, run: RagGenerationRun) -> None: ...

    async def update(self, run: RagGenerationRun) -> None: ...

    async def create_sources(
        self, run_id: uuid.UUID, sources: Sequence[Any]
    ) -> None: ...

    async def save_outcome(
        self, key_hash: str, outcome: RagGenerationOutcome
    ) -> None: ...


class InMemoryRagAuditStore:
    """Small deterministic store used by fakes and unit tests."""

    def __init__(self) -> None:
        self.runs: dict[uuid.UUID, RagGenerationRun] = {}
        self.outcomes: dict[str, RagGenerationOutcome] = {}
        self._pending: dict[str, tuple[str, uuid.UUID | None]] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self, key_hash: str, request_hash: str
    ) -> RagGenerationOutcome | None:
        async with self._lock:
            outcome = self.outcomes.get(key_hash)
            if outcome is not None and outcome.run.request_hash != request_hash:
                raise RagGenerationError("RAG_IDEMPOTENCY_KEY_MISMATCH")
            pending = self._pending.get(key_hash)
            if pending is not None:
                if pending[0] != request_hash:
                    raise RagGenerationError("RAG_IDEMPOTENCY_KEY_MISMATCH")
                raise RagGenerationError("RAG_GENERATION_IN_PROGRESS")
            if outcome is None:
                self._pending[key_hash] = (request_hash, None)
            return outcome

    async def create(self, run: RagGenerationRun) -> None:
        async with self._lock:
            self.runs[run.id] = run
            if run.idempotency_key_hash is not None:
                pending = self._pending.get(run.idempotency_key_hash)
                if pending is not None and pending[0] == run.request_hash:
                    self._pending[run.idempotency_key_hash] = (run.request_hash, run.id)

    async def update(self, run: RagGenerationRun) -> None:
        async with self._lock:
            self.runs[run.id] = run
            if (
                run.status is RagGenerationStatus.FAILED
                and run.idempotency_key_hash is not None
            ):
                self._pending.pop(run.idempotency_key_hash, None)

    async def create_sources(self, run_id: uuid.UUID, sources: Sequence[Any]) -> None:
        del run_id, sources

    async def save_outcome(self, key_hash: str, outcome: RagGenerationOutcome) -> None:
        async with self._lock:
            self.outcomes[key_hash] = outcome
            self.runs[outcome.run.id] = outcome.run
            self._pending.pop(key_hash, None)


class SQLAlchemyRagAuditStore:
    """Persistence adapter that opens only short transactions around each write."""

    def __init__(self, uow_factory: type[UnitOfWork] = UnitOfWork) -> None:
        self._uow_factory = uow_factory

    async def reserve(
        self, key_hash: str, request_hash: str
    ) -> RagGenerationOutcome | None:
        async with self._uow_factory() as uow:
            existing = await uow.rag_runs.find_by_idempotency_hash(key_hash)
            if existing is None:
                return None
            if existing.request_hash != request_hash:
                raise RagGenerationError("RAG_IDEMPOTENCY_KEY_MISMATCH")
            if existing.status is not RagGenerationStatus.SUCCEEDED:
                raise RagGenerationError("RAG_GENERATION_IN_PROGRESS")
            if existing.draft_id is None:
                raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
            draft = await uow.drafts.get_by_id(existing.draft_id)
            structured_model = await uow.rag_structured_drafts.get_by_run(existing.id)
            if draft is None or structured_model is None:
                raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
            structured = RagStructuredDraft.model_validate(
                structured_model.content_json
            )
            return RagGenerationOutcome(existing, structured, draft, tuple())

    async def create(self, run: RagGenerationRun) -> None:
        try:
            async with self._uow_factory() as uow:
                await uow.rag_runs.create(run)
        except IntegrityError as exc:
            raise RagGenerationError("RAG_GENERATION_IN_PROGRESS") from exc

    async def update(self, run: RagGenerationRun) -> None:
        async with self._uow_factory() as uow:
            await uow.rag_runs.update(run)

    async def create_sources(self, run_id: uuid.UUID, sources: Sequence[Any]) -> None:
        async with self._uow_factory() as uow:
            await uow.rag_sources.create_many(run_id, sources)

    async def save_outcome(self, key_hash: str, outcome: RagGenerationOutcome) -> None:
        del key_hash
        if outcome.draft is None or outcome.structured_draft is None:
            raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
        async with self._uow_factory() as uow:
            await uow.drafts.create(outcome.draft)
            await uow.rag_structured_drafts.create(
                run_id=outcome.run.id,
                draft_id=outcome.draft.id,
                structured=outcome.structured_draft,
            )
            snapshot = {
                "draft_id": str(outcome.draft.id),
                "draft_version": outcome.draft.version,
                "title": outcome.draft.title,
                "content": outcome.draft.content or "",
                "context_snapshot": outcome.draft.context_snapshot,
            }
            now = datetime.now(UTC)
            review = await uow.reviews.create(
                DocumentReview(
                    id=uuid.uuid4(),
                    draft_id=outcome.draft.id,
                    draft_version=outcome.draft.version,
                    review_snapshot=snapshot,
                    review_snapshot_sha256=sha256_json(snapshot),
                    status=ReviewStatus.OPEN,
                    opened_by="rag-system",
                    version=1,
                    opened_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            await uow.review_events.create(
                ReviewEvent(
                    id=uuid.uuid4(),
                    review_id=review.id,
                    draft_id=review.draft_id,
                    resource_type="REVIEW",
                    resource_id=str(review.id),
                    event_type="REVIEW_OPENED",
                    actor="rag-system",
                    request_id=outcome.run.request_id,
                    run_id=outcome.run.id,
                    draft_version=review.draft_version,
                    summary={"source": "RAG"},
                    created_at=now,
                )
            )
            await uow.rag_runs.update(outcome.run)


class RagGenerationService:
    """The generation state machine; external calls happen outside DB transactions."""

    def __init__(
        self,
        *,
        retrieval: RagRetrievalService,
        provider: StructuredGenerationProvider,
        audit: RagAuditStore | None = None,
        prompt_version: str = "rag-decree-v1",
        schema_repair_attempts: int = 1,
        generation_model: str = "qwen3.6:35b",
        embedding_model: str = "qwen3-embedding:4b-q4_K_M",
        embedding_dimensions: int = 2560,
        document_subtype: str = "designacion_transitoria",
        inference_coordinator: InferenceCoordinator | None = None,
    ) -> None:
        if generation_model != "qwen3.6:35b":
            raise ValueError("RAG_GENERATION_MODEL_INVALID")
        if (
            embedding_model != "qwen3-embedding:4b-q4_K_M"
            or embedding_dimensions != 2560
        ):
            raise ValueError("RAG_EMBEDDING_CONTRACT_INVALID")
        self._retrieval = retrieval
        self._provider = provider
        self._audit = audit or InMemoryRagAuditStore()
        self._prompt_builder = RagPromptBuilder(prompt_version)
        self._schema_repair_attempts = max(0, min(schema_repair_attempts, 1))
        self._generation_model = generation_model
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        if document_subtype not in {"designacion_transitoria", "decreto"}:
            raise ValueError("RAG_DOCUMENT_SUBTYPE_INVALID")
        self._document_subtype = document_subtype
        self._coordinator = inference_coordinator

    def _request_hash(self, request: RagDraftGenerationRequest) -> str:
        return sha256_json(
            {
                "template_id": str(request.template_id),
                "case_file_id": str(request.case_file_id),
                "variables": request.variables,
                "retrieval": request.retrieval.model_dump(mode="json"),
                "prompt_version": self._prompt_builder.version,
                "schema_version": 1,
                "embedding_model": self._embedding_model,
                "embedding_dimensions": self._embedding_dimensions,
                "generation_model": self._generation_model,
                "document_subtype": self._document_subtype,
            }
        )

    async def _fail(
        self,
        run: RagGenerationRun,
        code: str,
        *,
        retrieved_count: int = 0,
        selected_count: int = 0,
        schema_repair_count: int = 0,
        started: float,
    ) -> RagGenerationError:
        failed = replace(
            run,
            status=RagGenerationStatus.FAILED,
            draft_id=None,
            error_code=sanitize_error_code(code),
            retrieved_count=retrieved_count,
            selected_count=selected_count,
            schema_repair_count=schema_repair_count,
            finished_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            total_duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
        await self._audit.update(failed)
        return RagGenerationError(failed.error_code or "RAG_INTERNAL_ERROR")

    async def generate(
        self,
        request: RagDraftGenerationRequest,
        *,
        idempotency_key: str,
        request_id: str,
    ) -> RagGenerationOutcome:
        if not 16 <= len(idempotency_key) <= 128:
            raise RagGenerationError("RAG_INVALID_REQUEST")
        if not request_id.strip() or len(request_id) > 128:
            raise RagGenerationError("RAG_INVALID_REQUEST")
        started = time.monotonic()
        request_hash = self._request_hash(request)
        key_hash = sha256_text(idempotency_key)
        cached = await self._audit.reserve(key_hash, request_hash)
        if cached is not None:
            return cached
        query_variables = {
            "case_file_id": str(request.case_file_id),
            "template_id": str(request.template_id),
            **request.variables,
        }
        query = RagQueryBuilder(self._document_subtype).build(
            variables=query_variables,
            language=request.retrieval.language,
            organization=request.retrieval.organization,
        )
        run = RagGenerationRun(
            id=uuid.uuid4(),
            case_file_id=request.case_file_id,
            template_id=request.template_id,
            request_hash=request_hash,
            query_hash=query.query_hash,
            idempotency_key_hash=key_hash,
            prompt_version=self._prompt_builder.version,
            top_k=request.retrieval.top_k,
            candidate_pool_size=min(3 * request.retrieval.top_k, 50),
            minimum_score=request.retrieval.minimum_score,
            request_id=request_id,
            embedding_model=self._embedding_model,
            embedding_dimensions=self._embedding_dimensions,
            generation_model=self._generation_model,
        )
        try:
            await self._audit.create(run)
        except RagGenerationError as exc:
            if exc.code == "RAG_GENERATION_IN_PROGRESS":
                cached = await self._audit.reserve(key_hash, request_hash)
                if cached is not None:
                    return cached
            raise
        except Exception as exc:
            raise RagGenerationError("RAG_AUDIT_UNAVAILABLE") from exc
        run = replace(
            run, status=RagGenerationStatus.RETRIEVING, updated_at=datetime.now(UTC)
        )
        await self._audit.update(run)
        try:
            retrieval = await self._retrieval.retrieve(
                query.text,
                filters=query.filters,
                top_k=request.retrieval.top_k,
                candidate_pool_size=run.candidate_pool_size,
                minimum_score=request.retrieval.minimum_score,
            )
        except Exception as exc:
            raise await self._fail(
                run, "SEMANTIC_SEARCH_AUDIT_UNAVAILABLE", started=started
            ) from exc
        try:
            await self._audit.create_sources(run.id, retrieval.sources)
        except Exception as exc:
            raise await self._fail(
                run,
                "SEMANTIC_SEARCH_AUDIT_UNAVAILABLE",
                retrieved_count=len(retrieval.sources),
                started=started,
            ) from exc
        selected = tuple(
            source
            for source in retrieval.sources
            if source.disposition is RagSourceDisposition.SELECTED
        )
        if not selected:
            raise await self._fail(
                replace(run, retrieved_count=len(retrieval.sources)),
                "RAG_INSUFFICIENT_EVIDENCE",
                retrieved_count=len(retrieval.sources),
                selected_count=0,
                started=started,
            )
        run = replace(
            run,
            status=RagGenerationStatus.GENERATING,
            retrieved_count=len(retrieval.sources),
            selected_count=len(selected),
            context_hash=retrieval.context.context_hash,
            context_bytes=retrieval.context.context_bytes,
            context_tokens_estimate=retrieval.context.context_tokens_estimate,
            retrieval_duration_ms=retrieval.duration_ms,
            updated_at=datetime.now(UTC),
        )
        await self._audit.update(run)
        prompt = self._prompt_builder.build(
            query=query.text,
            context=retrieval.context.text,
            variables=request.variables,
        )
        run = replace(run, prompt_hash=sha256_text(prompt.user_message))
        await self._audit.update(run)
        repair_count = 0
        run = replace(
            run,
            status=RagGenerationStatus.VALIDATING,
            updated_at=datetime.now(UTC),
        )
        await self._audit.update(run)
        payload: dict[str, Any] | None = None
        validation_error = "RAG_OUTPUT_INVALID"
        for attempt in range(self._schema_repair_attempts + 1):
            try:
                active_prompt = prompt

                async def generate_call(
                    active_prompt: RagPrompt = active_prompt,
                ) -> dict[str, Any]:
                    raw = await self._provider.generate_structured(
                        system_message=active_prompt.system_message,
                        user_message=active_prompt.user_message,
                        schema=rag_generation_schema(),
                        temperature=0.1,
                        context=[
                            {
                                "citation_id": source.citation_id,
                                "external_id": source.external_id,
                                "title": source.title,
                                "publication_date": source.publication_date,
                                "section_type": source.section_type,
                                "source_url": source.source_url,
                            }
                            for source in selected
                        ],
                    )
                    return dict(raw)

                if self._coordinator is None:
                    raw = await generate_call()
                else:
                    raw = await self._coordinator.execute(
                        InferencePriority.INTERACTIVE,
                        generate_call,
                        timeout=300,
                    )
                raw["warnings"] = [_REVIEW_WARNING]
                raw["sources"] = [
                    {
                        "citation_id": source.citation_id,
                        "external_id": source.external_id,
                        "title": source.title,
                        "publication_date": source.publication_date,
                        "section_type": source.section_type,
                        "source_url": source.source_url,
                    }
                    for source in selected
                ]
                candidate = RagStructuredDraft.model_validate(raw)
                allowed = {source.citation_id for source in selected}
                if not set(candidate.citation_ids).issubset(allowed):
                    raise ValueError("RAG_UNKNOWN_CITATION")
                payload = candidate.model_dump(mode="json")
                break
            except (StructuredGenerationError, ValueError, TypeError) as exc:
                if isinstance(exc, ValidationError):
                    logger.warning(
                        "rag_validation_failed issues=%s attempt=%s",
                        [
                            {
                                "location": ".".join(
                                    str(part) for part in issue["loc"]
                                ),
                                "type": issue["type"],
                            }
                            for issue in exc.errors(include_input=False)
                        ][:20],
                        attempt + 1,
                    )
                else:
                    logger.warning(
                        "rag_generation_payload_failed category=%s code=%s attempt=%s",
                        type(exc).__name__,
                        (
                            exc.code
                            if isinstance(exc, StructuredGenerationError)
                            else "RAG_OUTPUT_INVALID"
                        ),
                        attempt + 1,
                    )
                validation_error = (
                    exc.code
                    if isinstance(exc, StructuredGenerationError)
                    else "RAG_OUTPUT_INVALID"
                )
                if attempt >= self._schema_repair_attempts:
                    raise await self._fail(
                        run,
                        validation_error,
                        retrieved_count=len(retrieval.sources),
                        selected_count=len(selected),
                        schema_repair_count=repair_count,
                        started=started,
                    ) from exc
                repair_count += 1
                prompt = replace(
                    prompt,
                    user_message=(
                        prompt.user_message
                        + "\n\nREPAIR_ERRORS=JSON/schema/citation validation failed; "
                        "return only valid JSON."
                    ),
                )
        if payload is None:
            raise await self._fail(run, "RAG_OUTPUT_INVALID", started=started)
        structured = RagStructuredDraft.model_validate(payload)
        now = datetime.now(UTC)
        draft = Draft(
            id=uuid.uuid4(),
            template_id=request.template_id,
            case_file_id=request.case_file_id,
            title=structured.title,
            content=structured.render_for_review(),
            status=DraftStatus.EN_REVISION,
            version=1,
            generation_number=1,
            context_snapshot={
                "rag_run_id": str(run.id),
                "structured_schema_version": 1,
            },
            context_hash=retrieval.context.context_hash,
            variables_used=request.variables,
            request_id=request_id,
            created_at=now,
            updated_at=now,
        )
        succeeded = replace(
            run,
            status=RagGenerationStatus.SUCCEEDED,
            draft_id=draft.id,
            schema_repair_count=repair_count,
            generation_duration_ms=max(
                0, int((time.monotonic() - started) * 1000) - retrieval.duration_ms
            ),
            validation_duration_ms=0,
            total_duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            finished_at=now,
            updated_at=now,
        )
        outcome = RagGenerationOutcome(succeeded, structured, draft, retrieval.sources)
        try:
            await self._audit.save_outcome(key_hash, outcome)
        except Exception as exc:
            raise await self._fail(
                succeeded,
                "RAG_AUDIT_UNAVAILABLE",
                retrieved_count=len(retrieval.sources),
                selected_count=len(selected),
                schema_repair_count=repair_count,
                started=started,
            ) from exc
        return outcome
