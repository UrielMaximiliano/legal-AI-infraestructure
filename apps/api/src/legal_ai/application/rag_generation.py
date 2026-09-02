"""Auditable orchestration of retrieval, structured generation and Draft creation."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar, cast

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.inference_coordinator import InferenceCoordinator
from legal_ai.application.rag_prompt import RagPrompt, RagPromptBuilder
from legal_ai.application.rag_query import RagQuery, RagQueryBuilder
from legal_ai.application.rag_retrieval import RagRetrievalResult, RagRetrievalService
from legal_ai.domain.draft import Draft
from legal_ai.domain.draft_document import DraftDocumentVersion
from legal_ai.domain.enums import DraftStatus
from legal_ai.domain.errors import DomainError
from legal_ai.domain.rag import (
    RagGenerationRun,
    RagGenerationStatus,
    RagRetrievedSource,
    RagSourceDisposition,
    sanitize_error_code,
    sha256_json,
    sha256_text,
)
from legal_ai.ports.embedding import InferencePriority
from legal_ai.ports.structured_generation import (
    StructuredGenerationError,
    StructuredGenerationProvider,
)
from legal_ai.schemas.document import LegalDocument
from legal_ai.schemas.rag import (
    RagDraftGenerationRequest,
    RagSource,
    RagStructuredDraft,
    rag_schema,
)

logger = logging.getLogger(__name__)

PayloadT = TypeVar("PayloadT")


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
            "RAG_GENERATION_CANCELLED": 409,
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
            "RAG_GENERATION_CANCELLED": "La generación fue cancelada.",
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


ProgressCallback = Callable[[str, RagGenerationRun | None], Awaitable[None]]
CancellationEvent = asyncio.Event


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
                run.status
                in {RagGenerationStatus.FAILED, RagGenerationStatus.CANCELLED}
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
            if existing.status in {
                RagGenerationStatus.FAILED,
                RagGenerationStatus.CANCELLED,
            }:
                return None
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
            version_repository = getattr(uow, "draft_document_versions", None)
            if version_repository is not None:
                await version_repository.create(
                    DraftDocumentVersion(
                        id=uuid.uuid4(),
                        draft_id=outcome.draft.id,
                        version=outcome.draft.version,
                        document=outcome.draft.document
                        or outcome.structured_draft.model_dump(mode="json"),
                        content=outcome.draft.content or "",
                        content_sha256=sha256_text(outcome.draft.content or ""),
                        source="AI_GENERATED",
                        edited_by="rag-system",
                        created_at=datetime.now(UTC),
                    )
                )
            await uow.rag_structured_drafts.create(
                run_id=outcome.run.id,
                draft_id=outcome.draft.id,
                structured=outcome.structured_draft,
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
        prompt_version: str = "rag-legal-document-v1",
        schema_repair_attempts: int = 1,
        generation_model: str = "qwen3.6:35b",
        embedding_model: str = "qwen3-embedding:4b-q4_K_M",
        embedding_dimensions: int = 2560,
        profile_code: str = "legacy",
        candidate_pool_size: int = 24,
        generation_context_length: int = 16_384,
        inference_coordinator: InferenceCoordinator | None = None,
    ) -> None:
        if generation_model != "qwen3.6:35b":
            raise ValueError("RAG_GENERATION_MODEL_INVALID")
        expected_contracts = {
            "legacy": ("qwen3-embedding:4b-q4_K_M", 2560),
            "imi_leg_06b": ("qwen3-embedding:0.6b", 1024),
        }
        expected = expected_contracts.get(profile_code)
        if expected is None or (embedding_model, embedding_dimensions) != expected:
            raise ValueError("RAG_EMBEDDING_CONTRACT_INVALID")
        if candidate_pool_size < 3 or candidate_pool_size > 50:
            raise ValueError("RAG_RETRIEVAL_LIMIT_INVALID")
        if generation_context_length <= 0:
            raise ValueError("OLLAMA_GENERATION_CONTEXT_INVALID")
        self._retrieval = retrieval
        self._provider = provider
        self._audit = audit or InMemoryRagAuditStore()
        self._prompt_builder = RagPromptBuilder(prompt_version)
        self._schema_repair_attempts = max(0, min(schema_repair_attempts, 1))
        self._generation_model = generation_model
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._profile_code = profile_code
        self._candidate_pool_size = candidate_pool_size
        self._generation_context_length = generation_context_length
        self._coordinator = inference_coordinator

    def _request_hash(
        self,
        request: RagDraftGenerationRequest,
        query_context: dict[str, str | None] | None = None,
    ) -> str:
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
                "profile_code": self._profile_code,
                "query_context": query_context or {},
            }
        )

    @staticmethod
    def _effective_variables(
        request: RagDraftGenerationRequest,
        query_context: dict[str, str | None] | None,
    ) -> dict[str, str]:
        """Complete server-owned template variables without expanding the form."""

        variables = {key: str(value) for key, value in request.variables.items()}
        case_number = (query_context or {}).get("case_number")
        if case_number and not variables.get("expediente"):
            variables["expediente"] = case_number
        date_value = variables.get("fecha", "")
        year_match = re.search(r"\b(\d{4})\b", date_value)
        if year_match and not variables.get("anio"):
            variables["anio"] = year_match.group(1)
        return variables

    @staticmethod
    def _replace_template_variables(
        payload: PayloadT,
        variables: dict[str, str],
    ) -> PayloadT:
        """Replace only known placeholders in the validated model response."""

        if isinstance(payload, str):
            return cast(
                "PayloadT",
                re.sub(
                    r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}",
                    lambda match: (
                        variables[match.group(1)]
                        if variables.get(match.group(1), "").strip()
                        else match.group(0)
                    ),
                    payload,
                ),
            )
        if isinstance(payload, list):
            return cast(
                "PayloadT",
                [
                    RagGenerationService._replace_template_variables(item, variables)
                    for item in payload
                ],
            )
        if isinstance(payload, dict):
            return cast(
                "PayloadT",
                {
                    key: RagGenerationService._replace_template_variables(
                        value, variables
                    )
                    for key, value in payload.items()
                },
            )
        return payload

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

    async def _cancel(self, run: RagGenerationRun, started: float) -> None:
        cancelled = replace(
            run,
            status=RagGenerationStatus.CANCELLED,
            draft_id=None,
            error_code="RAG_GENERATION_CANCELLED",
            finished_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            total_duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
        try:
            await self._audit.update(cancelled)
        except Exception:
            # Cancellation must never mask the original task cancellation.
            return

    async def _check_cancelled(
        self,
        run: RagGenerationRun,
        started: float,
        cancel_event: CancellationEvent | None,
    ) -> None:
        if cancel_event is not None and cancel_event.is_set():
            await self._cancel(run, started)
            raise RagGenerationError("RAG_GENERATION_CANCELLED")

    async def _notify(
        self,
        callback: ProgressCallback | None,
        phase: str,
        run: RagGenerationRun | None,
    ) -> None:
        if callback is None:
            return
        try:
            await callback(phase, run)
        except Exception:
            # A disconnected SSE subscriber does not alter the legal operation.
            return

    def _validate_request(self, idempotency_key: str, request_id: str) -> None:
        if not 16 <= len(idempotency_key) <= 128:
            raise RagGenerationError("RAG_INVALID_REQUEST")
        if not request_id.strip() or len(request_id) > 128:
            raise RagGenerationError("RAG_INVALID_REQUEST")

    def _build_query(
        self,
        request: RagDraftGenerationRequest,
        query_context: dict[str, str | None] | None = None,
    ) -> RagQuery:
        query_variables = {
            "case_file_id": str(request.case_file_id),
            "template_id": str(request.template_id),
            **request.variables,
        }
        return RagQueryBuilder().build(
            variables=query_variables,
            document_type=(query_context or {}).get("document_type"),
            document_subtype=(query_context or {}).get("document_subtype"),
            jurisdiction=(query_context or {}).get("jurisdiction"),
            language=request.retrieval.language,
            organization=(
                query_context["organization"]
                if query_context is not None and "organization" in query_context
                else request.retrieval.organization
            ),
        )

    def _new_run(
        self,
        request: RagDraftGenerationRequest,
        query: RagQuery,
        *,
        request_hash: str,
        key_hash: str,
        request_id: str,
    ) -> RagGenerationRun:
        return RagGenerationRun(
            id=uuid.uuid4(),
            case_file_id=request.case_file_id,
            template_id=request.template_id,
            request_hash=request_hash,
            query_hash=query.query_hash,
            idempotency_key_hash=key_hash,
            prompt_version=self._prompt_builder.version,
            top_k=request.retrieval.top_k,
            candidate_pool_size=max(
                request.retrieval.top_k,
                min(self._candidate_pool_size, 50),
            ),
            minimum_score=request.retrieval.minimum_score,
            request_id=request_id,
            embedding_model=self._embedding_model,
            embedding_dimensions=self._embedding_dimensions,
            profile_code=self._profile_code,
            generation_model=self._generation_model,
        )

    async def _retrieve_and_audit(
        self,
        run: RagGenerationRun,
        query: RagQuery,
        request: RagDraftGenerationRequest,
        *,
        started: float,
        cancel_event: CancellationEvent | None,
    ) -> tuple[
        RagGenerationRun,
        RagRetrievalResult,
        tuple[RagRetrievedSource, ...],
    ]:
        """Recupera evidencia, audita las fuentes y selecciona las citables."""

        await self._check_cancelled(run, started, cancel_event)
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
        await self._check_cancelled(run, started, cancel_event)
        return run, retrieval, selected

    async def _generate_structured(
        self,
        run: RagGenerationRun,
        query: RagQuery,
        request: RagDraftGenerationRequest,
        retrieval: RagRetrievalResult,
        selected: tuple[RagRetrievedSource, ...],
        *,
        started: float,
        cancel_event: CancellationEvent | None,
        template_body: str | None = None,
        target_document_type: str | None = None,
    ) -> tuple[RagGenerationRun, RagStructuredDraft, int]:
        """Construye el prompt y genera la salida estructurada con reparación."""

        prompt = self._prompt_builder.build(
            query=query.text,
            context=retrieval.context.text,
            variables=request.variables,
            document_type=target_document_type
            or query.filters.get("document_type", "documento"),
            document_subtype=query.filters.get("document_subtype", "expediente"),
            template_body=template_body,
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
            await self._check_cancelled(run, started, cancel_event)
            output_shape: dict[str, object] | None = None
            try:
                active_prompt = prompt

                async def generate_call(
                    active_prompt: RagPrompt = active_prompt,
                ) -> dict[str, Any]:
                    generation_kwargs: dict[str, Any] = {
                        "system_message": active_prompt.system_message,
                        "user_message": active_prompt.user_message,
                        "schema": rag_schema(),
                        "temperature": 0.1,
                        "context": [
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
                    }
                    if getattr(self._provider, "supports_num_ctx", False):
                        generation_kwargs["num_ctx"] = self._generation_context_length
                    raw = await self._provider.generate_structured(
                        **generation_kwargs,
                    )
                    normalized = dict(
                        self._replace_template_variables(raw, request.variables)
                    )
                    if target_document_type == "nota_inicio":
                        # The institutional note has no operative section. Keep
                        # the model responsible for the prose, while enforcing
                        # the server-owned structural fields. Some local models
                        # repeat the two paragraphs in both legacy buckets; the
                        # note editor has one body, so merge those buckets and
                        # retain the first two unique paragraphs.
                        merged_paragraphs: dict[str, dict[str, Any]] = {}
                        for bucket in ("visto", "considerandos"):
                            value = normalized.get(bucket, [])
                            if not isinstance(value, list):
                                continue
                            for paragraph in value:
                                if not isinstance(paragraph, dict):
                                    continue
                                text = str(paragraph.get("text", "")).strip()
                                if not text:
                                    continue
                                key = " ".join(text.split())
                                existing = merged_paragraphs.get(key)
                                if existing is None:
                                    merged_paragraphs[key] = {
                                        "text": text,
                                        "citation_ids": list(
                                            paragraph.get("citation_ids", [])
                                        ),
                                    }
                                else:
                                    existing["citation_ids"] = list(
                                        dict.fromkeys(
                                            [
                                                *existing["citation_ids"],
                                                *paragraph.get("citation_ids", []),
                                            ]
                                        )
                                    )
                        normalized.update(
                            {
                                "title": "INFORME DE INICIO DE ACTUACIONES",
                                "visto": list(merged_paragraphs.values())[:2],
                                "considerandos": [],
                                "articles": [],
                                "dispositive_intro": "",
                                "closing": "",
                                "authority": "Dirección de Gestión Administrativa",
                                "signature": "",
                                "warnings": [
                                    "BORRADOR NO VINCULANTE; REVISIÓN HUMANA "
                                    "OBLIGATORIA."
                                ],
                            }
                        )
                    return normalized

                if self._coordinator is None:
                    raw = await generate_call()
                else:
                    raw = await self._coordinator.execute(
                        InferencePriority.INTERACTIVE,
                        generate_call,
                        timeout=300,
                    )
                output_shape = {
                    "keys": sorted(raw),
                    "list_lengths": {
                        key: len(value)
                        for key, value in raw.items()
                        if isinstance(value, list)
                    },
                }
                candidate = RagStructuredDraft.model_validate(raw)
                if (
                    target_document_type == "disposicion"
                    and len(candidate.articles) != 6
                ):
                    raise ValueError("RAG_TEMPLATE_STRUCTURE_INVALID")
                if target_document_type == "nota_inicio" and candidate.articles:
                    raise ValueError("RAG_TEMPLATE_STRUCTURE_INVALID")
                selected_by_citation = {
                    source.citation_id: source for source in selected
                }
                if not set(candidate.citation_ids).issubset(selected_by_citation):
                    raise ValueError("RAG_UNKNOWN_CITATION")
                candidate = candidate.model_copy(
                    update={
                        "sources": [
                            RagSource.model_validate(
                                {
                                    "citation_id": source.citation_id,
                                    "external_id": source.external_id,
                                    "title": source.title,
                                    "publication_date": source.publication_date,
                                    "section_type": source.section_type,
                                    "source_url": source.source_url,
                                }
                            )
                            for source in (
                                selected_by_citation[citation_id]
                                for citation_id in candidate.citation_ids
                            )
                        ]
                    }
                )
                payload = candidate.model_dump(mode="json")
                break
            except (StructuredGenerationError, ValueError, TypeError) as exc:
                logger.warning(
                    "Structured RAG output rejected error_type=%s provider_code=%s "
                    "attempt=%s output_shape=%s validation_locations=%s",
                    type(exc).__name__,
                    getattr(exc, "code", None),
                    attempt,
                    output_shape,
                    (
                        [error.get("loc") for error in exc.errors()]
                        if isinstance(exc, ValidationError)
                        else None
                    ),
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
                repair_hint = (
                    "JSON/schema/citation validation failed; return only valid JSON."
                )
                if isinstance(exc, ValidationError):
                    locations = {
                        ".".join(str(part) for part in error.get("loc", ()))
                        for error in exc.errors()
                    }
                    if any(location == "warnings" for location in locations):
                        repair_hint = (
                            "The warnings field must contain exactly one unique, "
                            "non-empty warning that includes both "
                            "'BORRADOR NO VINCULANTE' and "
                            "'REVISIÓN HUMANA OBLIGATORIA'. Return only valid JSON."
                        )
                    else:
                        repair_hint = (
                            "Validation failed in fields: "
                            + ", ".join(sorted(locations))
                            + ". Return only valid JSON matching the schema."
                        )
                prompt = replace(
                    prompt,
                    user_message=(
                        prompt.user_message
                        + f"\n\nREPAIR_ERRORS={repair_hint}"
                    ),
                )
        if payload is None:
            raise await self._fail(run, "RAG_OUTPUT_INVALID", started=started)
        return run, RagStructuredDraft.model_validate(payload), repair_count

    async def _persist_outcome(
        self,
        run: RagGenerationRun,
        request: RagDraftGenerationRequest,
        *,
        request_id: str,
        key_hash: str,
        retrieval: RagRetrievalResult,
        selected: tuple[RagRetrievedSource, ...],
        structured: RagStructuredDraft,
        repair_count: int,
        document_type: str,
        started: float,
        cancel_event: CancellationEvent | None,
    ) -> RagGenerationOutcome:
        """Persiste el resultado auditado (draft, revisión y run); fail-closed."""

        await self._check_cancelled(run, started, cancel_event)
        now = datetime.now(UTC)
        document = LegalDocument.model_validate(
            {
                **structured.model_dump(mode="json"),
            "document_type": document_type,
            }
        )
        document_payload = document.model_dump(mode="json")
        draft = Draft(
            id=uuid.uuid4(),
            template_id=request.template_id,
            case_file_id=request.case_file_id,
            title=structured.title,
            content=structured.render_for_review(),
            document=document_payload,
            document_type=document_type,
            status=DraftStatus.GENERADO,
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

    async def generate(
        self,
        request: RagDraftGenerationRequest,
        *,
        idempotency_key: str,
        request_id: str,
        query_context: dict[str, str | None] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_event: CancellationEvent | None = None,
        template_body: str | None = None,
        target_document_type: str | None = None,
    ) -> RagGenerationOutcome:
        """Máquina de estados: reserva → recuperación → generación → auditoría."""

        self._validate_request(idempotency_key, request_id)
        started = time.monotonic()
        effective_request = request.model_copy(
            update={
                "variables": self._effective_variables(request, query_context),
            }
        )
        request_hash = self._request_hash(effective_request, query_context)
        key_hash = sha256_text(idempotency_key)
        cached = await self._audit.reserve(key_hash, request_hash)
        if cached is not None:
            return cached
        query = self._build_query(effective_request, query_context)
        run = self._new_run(
            effective_request,
            query,
            request_hash=request_hash,
            key_hash=key_hash,
            request_id=request_id,
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
        try:
            await self._notify(progress_callback, "queued", run)
            await self._check_cancelled(run, started, cancel_event)
            run = replace(
                run,
                status=RagGenerationStatus.RETRIEVING,
                updated_at=datetime.now(UTC),
            )
            await self._audit.update(run)
            await self._notify(progress_callback, "retrieving", run)

            run, retrieval, selected = await self._retrieve_and_audit(
                run,
                query,
                effective_request,
                started=started,
                cancel_event=cancel_event,
            )
            await self._notify(progress_callback, "generating", run)
            run, structured, repair_count = await self._generate_structured(
                run,
                query,
                effective_request,
                retrieval,
                selected,
                started=started,
                cancel_event=cancel_event,
                template_body=template_body,
                target_document_type=target_document_type,
            )
            await self._notify(progress_callback, "validating", run)
            await self._check_cancelled(run, started, cancel_event)
            return await self._persist_outcome(
                run,
                effective_request,
                request_id=request_id,
                key_hash=key_hash,
                retrieval=retrieval,
                selected=selected,
                structured=structured,
                repair_count=repair_count,
                document_type=target_document_type
                or (query_context or {}).get("document_type")
                or "otros",
                started=started,
                cancel_event=cancel_event,
            )
        except asyncio.CancelledError:
            await self._cancel(run, started)
            raise
