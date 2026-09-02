"""HTTP endpoints for auditable RAG draft generation."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import StreamingResponse

from legal_ai.adapters.database.dispositions_rag_unit_of_work import (
    DispositionsRagUnitOfWork,
)
from legal_ai.adapters.database.imi_core import ImiCoreUnitOfWork
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.ollama.structured_generation import (
    OllamaStructuredGenerationProvider,
)
from legal_ai.adapters.ollama_embedding import OllamaEmbeddingAdapter
from legal_ai.application.draft_service import (
    CaseFileNotFoundError,
    TemplateInactiveError,
    TemplateNotFoundError,
)
from legal_ai.application.imi_rag_audit import ImiRagAuditStore
from legal_ai.application.inference_coordinator import InferenceCoordinator
from legal_ai.application.rag_context import ContextAssembler
from legal_ai.application.rag_generation import (
    RagGenerationError,
    RagGenerationOutcome,
    RagGenerationService,
    SQLAlchemyRagAuditStore,
)
from legal_ai.application.rag_retrieval import RagRetrievalService
from legal_ai.config import settings
from legal_ai.domain.errors import DomainError
from legal_ai.domain.rag import RagGenerationRun
from legal_ai.ports.embedding import InferencePriority
from legal_ai.ports.structured_generation import StructuredGenerationError
from legal_ai.schemas.rag import (
  RagDraftGenerationRequest,
  RagDraftGenerationResponse,
  RagDraftSummary,
  RagGenerationSummary,
  RagRetrievalSummary,
  RagRunResponse,
  RagRunSourceResponse,
  RagSource,
  RagTextRewriteRequest,
  RagTextRewriteResponse,
)

router = APIRouter(tags=["rag"])
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
_TEMPLATE_VARIABLE = re.compile(r"{{\s*([A-Za-z0-9._~-]+)\s*}}")
_CONCEPT_FACT_MARKERS = re.compile(
    r"\b(?:ley|decreto|resoluci[oó]n|expediente|art[ií]culo|programa|jurisdicci[oó]n|"
    r"partida|sinep|presidencia|ministerio|secretar[ií]a)\b",
    re.IGNORECASE,
)
_CONCEPT_SENTENCE_START = re.compile(
    r"^(?:en\s+relaci[oó]n|se\s+(?:establece|dispone|designa|autoriza)|que\s+)",
    re.IGNORECASE,
)
_NOTE_MASCULINE_PHRASE_START = re.compile(
    r"^(?:proceso|procedimiento|tr[aá]mite|servicio|pago|suministro|mantenimiento|"
    r"desarrollo|apoyo|asesoramiento|otorgamiento|reconocimiento|cumplimiento)\b",
    re.IGNORECASE,
)
_REWRITE_STOP_WORDS = {
    "como",
    "para",
    "sobre",
    "tareas",
    "trabajos",
    "mediante",
    "instituto",
}


def _rewrite_content_tokens(value: str) -> set[str]:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) >= 4 and token not in _REWRITE_STOP_WORDS
    }
_coordinator_lock = threading.Lock()
_shared_coordinator: InferenceCoordinator | None = None


@dataclass
class _ActiveRagRun:
    task: asyncio.Task[RagGenerationOutcome]
    cancel_event: asyncio.Event


def _validate_concept_rewrite(original: str, rewritten: object) -> str | None:
    """Accept only a short noun phrase that cannot add legal or factual claims."""

    if not isinstance(rewritten, str):
        return None
    clean = rewritten.strip().rstrip(".;")
    if not clean or len(clean) > 500 or "\n" in clean or "\r" in clean:
        return None
    if _CONCEPT_SENTENCE_START.search(clean):
        return None
    original_numbers = set(re.findall(r"\d+(?:[.,/-]\d+)*", original))
    rewritten_numbers = set(re.findall(r"\d+(?:[.,/-]\d+)*", clean))
    if not rewritten_numbers.issubset(original_numbers):
        return None
    original_markers = {
        match.group(0).casefold() for match in _CONCEPT_FACT_MARKERS.finditer(original)
    }
    rewritten_markers = {
        match.group(0).casefold() for match in _CONCEPT_FACT_MARKERS.finditer(clean)
    }
    if not rewritten_markers.issubset(original_markers):
        return None
    original_tokens = _rewrite_content_tokens(original)
    rewritten_tokens = _rewrite_content_tokens(clean)
    if original_tokens and (
        len(original_tokens & rewritten_tokens) / len(original_tokens) < 0.5
    ):
        return None
    return clean


def _rewrite_prompt(target_document_type: str) -> str:
    """Return the field-specific rewrite contract for an IMI template."""

    if target_document_type == "nota_inicio":
        field_contract = (
            "el campo Razón de la actuación de una Nota de Inicio. La frase debe "
            "expresar el motivo concreto por el cual se inician las actuaciones y "
            "poder leerse inmediatamente después de 'por el'. Debe comenzar con una "
            "construcción nominal masculina; ante acciones como incorporación, "
            "contratación o adquisición, comienza exactamente con 'proceso de'"
        )
    else:
        field_contract = (
            "el campo Concepto de una Disposición por Fondo Permanente. La frase "
            "debe describir el objeto concreto del pago y poder leerse inmediatamente "
            "después de 'por el'"
        )

    return (
        "Eres un asistente de redacción jurídica del Instituto de Modernización "
        "e Innovación. Devuelve exclusivamente un objeto JSON con las claves "
        "text y citation_ids. Tu única tarea es convertir el texto del usuario "
        f"en UNA frase nominal breve para {field_contract}. No redactes oraciones, "
        "fundamentos, antecedentes ni artículos. Cuando corresponda, puede comenzar "
        "con 'servicio de', 'adquisición de', 'contratación de' o una construcción "
        "nominal equivalente. Conserva exactamente el objeto, nombres, cantidades y "
        "alcance aportados por el usuario. Está terminantemente prohibido agregar "
        "normas, organismos, cargos, partidas, fechas, porcentajes, números, "
        "obligaciones o cualquier otro hecho tomado de las fuentes. Las fuentes "
        "recuperadas son únicamente referencias de vocabulario y estilo jurídico. "
        "citation_ids debe contener únicamente identificadores recuperados que hayan "
        "resultado útiles para esa reformulación."
    )


def _normalize_rewrite_for_target(text: str, target_document_type: str) -> str:
    """Keep Nota de Inicio output grammatical after its fixed 'por el' text."""

    if (
        target_document_type == "nota_inicio"
        and _NOTE_MASCULINE_PHRASE_START.search(text) is None
    ):
        return f"proceso de {text}"
    return text


_active_runs: dict[UUID, _ActiveRagRun] = {}


class RagRunNotFoundError(DomainError):
    code = "RAG_RUN_NOT_FOUND"
    status_code = 404
    default_message = "La ejecución RAG solicitada no existe"


def _allowed_template_variables(template: object) -> set[str]:
    """Return required and body-declared variables accepted by generation."""

    required = getattr(template, "variables", ())
    body = getattr(template, "body_template", "") or ""
    return set(required) | set(_TEMPLATE_VARIABLE.findall(body))


def rag_idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if value is None or _SAFE_KEY.fullmatch(value) is None:
        raise RagGenerationError("RAG_INVALID_REQUEST")
    return value


def _get_shared_coordinator() -> InferenceCoordinator:
    """Return the process-wide monoslot coordinator used by every RAG request."""

    global _shared_coordinator
    with _coordinator_lock:
        if _shared_coordinator is None:
            _shared_coordinator = InferenceCoordinator(
                max_queue_size=32, wait_timeout=30
            )
        return _shared_coordinator


async def close_rag_coordinator() -> None:
    """Close the shared coordinator during application shutdown only."""

    global _shared_coordinator
    with _coordinator_lock:
        coordinator = _shared_coordinator
        _shared_coordinator = None
    if coordinator is not None:
        await coordinator.close()


def _build_service() -> tuple[RagGenerationService, InferenceCoordinator]:
    profile = settings.rag_profile
    is_imi = profile.code == "imi_leg_06b"
    coordinator = _get_shared_coordinator()
    embedding = OllamaEmbeddingAdapter(
        base_url=settings.ollama.base_url,
        api_token=settings.ollama.api_token,
        model=profile.embedding_model,
        dimensions=profile.embedding_dimensions,
        timeout_seconds=settings.corpus.embedding_timeout_seconds,
        endpoint=settings.ollama.endpoint,
        context_length=profile.embedding_context_length,
        contract_model=profile.embedding_model,
        contract_dimensions=profile.embedding_dimensions,
    )
    retrieval = RagRetrievalService(
        uow_factory=DispositionsRagUnitOfWork if is_imi else UnitOfWork,
        embedding_provider=embedding,
        inference_coordinator=coordinator,
        context_assembler=ContextAssembler(
            max_bytes=settings.rag.max_context_bytes,
            max_tokens_estimate=profile.rag_context_length,
        ),
        embedding_model=profile.embedding_model,
        embedding_dimensions=profile.embedding_dimensions,
        embedding_timeout_seconds=settings.corpus.embedding_timeout_seconds,
        max_chunks_per_document=settings.rag.max_chunks_per_document,
        max_chunks_per_section=settings.rag.max_chunks_per_section,
    )
    provider = OllamaStructuredGenerationProvider(
        base_url=settings.rag.generation_base_url,
        api_token=settings.rag.generation_token,
        model=settings.rag.generation_model,
        endpoint=settings.rag.generation_endpoint,
        timeout_seconds=settings.rag.generation_timeout_seconds,
        max_retries=settings.rag.generation_max_retries,
        generation_context_length=profile.generation_context_length,
    )
    return (
        RagGenerationService(
            retrieval=retrieval,
            provider=provider,
            audit=ImiRagAuditStore() if is_imi else SQLAlchemyRagAuditStore(),
            prompt_version=settings.rag.prompt_version,
            schema_repair_attempts=settings.rag.schema_repair_attempts,
            generation_model=profile.generation_model,
            embedding_model=profile.embedding_model,
            embedding_dimensions=profile.embedding_dimensions,
            profile_code=profile.code,
            candidate_pool_size=profile.candidate_pool_size,
            generation_context_length=profile.generation_context_length,
            inference_coordinator=coordinator,
        ),
        coordinator,
    )


@router.post(
    "/api/v1/rag/drafts/generate",
    response_model=RagDraftGenerationResponse,
    status_code=201,
)
async def generate_rag_draft(
    request: Request,
    response: Response,
    body: RagDraftGenerationRequest,
    idempotency_key: str = Depends(rag_idempotency_key),
) -> RagDraftGenerationResponse:
    template, case_file = await _validate_generation_context(body)

    service, _coordinator = _build_service()
    outcome = await service.generate(
        body,
        idempotency_key=idempotency_key,
        request_id=str(getattr(request.state, "request_id", "")),
        query_context=_query_context(template, case_file),
        template_body=getattr(template, "body_template", None),
        target_document_type=_enum_value(
            getattr(template, "document_type", None), "disposicion"
        ),
    )
    response.status_code = 201
    return _result_response(str(getattr(request.state, "request_id", "")), outcome)


async def _validate_generation_context(
    body: RagDraftGenerationRequest,
) -> tuple[object, object]:
    template, case_file = await _validate_reference_context(
        body.template_id, body.case_file_id
    )
    missing = set(getattr(template, "variables", ())) - set(body.variables)
    if missing:
        raise RagGenerationError("MISSING_REQUIRED_VARIABLES")
    unexpected = set(body.variables) - _allowed_template_variables(template)
    if unexpected:
        raise RagGenerationError("RAG_INVALID_REQUEST")
    return template, case_file


async def _validate_reference_context(
    template_id: UUID, case_file_id: UUID
) -> tuple[object, object]:
    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as uow:
            if uow.core is None:
                raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
            template = await uow.core.get_template(template_id)
            if template is None:
                raise TemplateNotFoundError(str(template_id))
            if not template.is_active:
                raise TemplateInactiveError(str(template_id))
            case_file = await uow.core.get_case_file(case_file_id)
            if case_file is None:
                raise CaseFileNotFoundError(str(case_file_id))
            return template, case_file
    async with UnitOfWork() as uow:
        template = await uow.templates.get_by_id(template_id)
        if template is None:
            raise TemplateNotFoundError(str(template_id))
        if not template.is_active:
            raise TemplateInactiveError(str(template_id))
        case_file = await uow.case_files.get_by_id(case_file_id)
        if case_file is None:
            raise CaseFileNotFoundError(str(case_file_id))
        return template, case_file


async def _validate_template_context(template_id: UUID) -> object:
    """Validate the template used by field-only rewriting."""

    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as uow:
            if uow.core is None:
                raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
            template = await uow.core.get_template(template_id)
    else:
        async with UnitOfWork() as uow:
            template = await uow.templates.get_by_id(template_id)

    if template is None:
        raise TemplateNotFoundError(str(template_id))
    if not template.is_active:
        raise TemplateInactiveError(str(template_id))
    return template


def _query_context(
    template: object, case_file: object | None
) -> dict[str, str | None]:
    """Return source-corpus filters without conflating IMI with source org."""

    if settings.rag_profile.code == "imi_leg_06b":
        # The isolated index contains reviewed national decrees. IMI is the
        # consuming organization, not a source-organization filter.
        return {
            "document_type": "decreto",
            "document_subtype": None,
            "jurisdiction": "nacion",
            "organization": None,
            "case_number": getattr(case_file, "case_number", None),
            "target_document_type": _enum_value(
                getattr(template, "document_type", None), "disposicion"
            ),
            "template_body": getattr(template, "body_template", None),
        }
    return {
        "document_type": _enum_value(
            getattr(template, "document_type", None), "decreto"
        ),
        "document_subtype": _enum_value(
            getattr(case_file, "case_type", None), "designacion_transitoria"
        ),
        "jurisdiction": "corrientes",
        "case_number": getattr(case_file, "case_number", None),
        "target_document_type": _enum_value(
            getattr(template, "document_type", None), "decreto"
        ),
        "template_body": getattr(template, "body_template", None),
    }


def _enum_value(value: object, fallback: str) -> str:
    candidate = getattr(value, "value", value)
    return str(candidate) if candidate is not None else fallback


def _result_response(
    request_id: str, outcome: RagGenerationOutcome
) -> RagDraftGenerationResponse:
    if outcome.draft is None or outcome.structured_draft is None:
        raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
    draft = outcome.draft
    return RagDraftGenerationResponse(
        request_id=request_id,
        rag_run_id=outcome.run.id,
        draft=RagDraftSummary(
            id=draft.id,
            template_id=draft.template_id,
            case_file_id=draft.case_file_id,
            title=draft.title,
            content=draft.content or "",
            status=draft.status.value,
            version=draft.version,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        ),
        structured_draft=outcome.structured_draft,
        retrieval=RagRetrievalSummary(
            result_count=outcome.run.retrieved_count,
            selected_count=outcome.run.selected_count,
        ),
        generation=RagGenerationSummary(
            model=outcome.run.generation_model,
            prompt_version=outcome.run.prompt_version,
            schema_version=outcome.run.schema_version,
        ),
    )


@router.post(
    "/api/v1/rag/text/rewrite",
    response_model=RagTextRewriteResponse,
    status_code=200,
)
async def rewrite_rag_text(
    request: Request,
    body: RagTextRewriteRequest,
) -> RagTextRewriteResponse:
    """Rewrite one field with reviewed evidence, without creating a draft."""

    if body.case_file_id is None:
        template = await _validate_template_context(body.template_id)
        case_file = None
    else:
        template, case_file = await _validate_reference_context(
            body.template_id, body.case_file_id
        )
    context = _query_context(template, case_file)
    target_document_type = str(context.get("target_document_type") or "disposicion")
    filters = {
        key: value
        for key, value in {
            "document_type": context.get("document_type"),
            "document_subtype": context.get("document_subtype"),
            "jurisdiction": context.get("jurisdiction"),
            "review_status": "REVIEWED",
            "evaluation_split": "INDEX_90",
        }.items()
        if value
    }
    service, coordinator = _build_service()
    try:
        retrieval = await service._retrieval.retrieve(  # noqa: SLF001
            body.text,
            filters=filters,
            top_k=body.retrieval.top_k,
            candidate_pool_size=max(body.retrieval.top_k, 24),
            minimum_score=body.retrieval.minimum_score,
        )
        selected = tuple(
            source
            for source in retrieval.sources
            if source.disposition.value == "SELECTED"
        )
        if not selected:
            raise RagGenerationError("RAG_INSUFFICIENT_EVIDENCE")
        source_context = "\n\n".join(
            f"[{source.citation_id}] {source.title}\n{source.excerpt}"
            for source in selected
        )
        system_message = _rewrite_prompt(target_document_type)
        user_message = (
            "REQUEST_DATA_BEGIN\n"
            f"texto_usuario={body.text}\n"
            "REQUEST_DATA_END\n"
            "EVIDENCE_DATA_BEGIN\n"
            f"{source_context}\n"
            "EVIDENCE_DATA_END"
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "citation_ids"],
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 500},
                "citation_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "pattern": "^SRC-[0-9][0-9][0-9]$"},
                },
            },
        }

        async def generate() -> Any:
            return await service._provider.generate_structured(  # noqa: SLF001
                system_message=system_message,
                user_message=user_message,
                schema=schema,
                temperature=0.0,
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
                num_ctx=service._generation_context_length,  # noqa: SLF001
            )

        raw = await coordinator.execute(
            InferencePriority.INTERACTIVE,
            generate,
            timeout=300,
        )
        rewritten = raw.get("text") if isinstance(raw, dict) else None
        validated_rewrite = _validate_concept_rewrite(body.text, rewritten)
        if validated_rewrite is not None:
            validated_rewrite = _normalize_rewrite_for_target(
                validated_rewrite,
                target_document_type,
            )
        citation_ids = raw.get("citation_ids") if isinstance(raw, dict) else None
        available = {source.citation_id for source in selected}
        if (
            validated_rewrite is None
            or not isinstance(citation_ids, list)
            or not citation_ids
            or not all(
                isinstance(item, str) and item in available for item in citation_ids
            )
        ):
            raise RagGenerationError("RAG_OUTPUT_INVALID")
        selected_by_id = {source.citation_id: source for source in selected}
        return RagTextRewriteResponse(
            request_id=str(getattr(request.state, "request_id", "")),
            text=validated_rewrite,
            citation_ids=list(dict.fromkeys(citation_ids)),
            sources=[
                RagSource.model_validate(
                    {
                        "citation_id": citation_id,
                        "external_id": selected_by_id[citation_id].external_id,
                        "title": selected_by_id[citation_id].title,
                        "publication_date": (
                            selected_by_id[citation_id].publication_date
                        ),
                        "section_type": selected_by_id[citation_id].section_type,
                        "source_url": selected_by_id[citation_id].source_url,
                    }
                )
                for citation_id in dict.fromkeys(citation_ids)
            ],
            retrieval=RagRetrievalSummary(
                result_count=len(retrieval.sources),
                selected_count=len(selected),
                embedding_model=retrieval.embedding_model,
                embedding_dimensions=retrieval.embedding_dimensions,
            ),
            generation=RagGenerationSummary(
                model=service._generation_model,  # noqa: SLF001
                prompt_version=(
                    f"{settings.rag.prompt_version}:text-rewrite:"
                    f"{target_document_type}"
                ),
                schema_version=1,
            ),
        )
    except StructuredGenerationError as exc:
        raise RagGenerationError(exc.code) from exc
    except TimeoutError as exc:
        raise RagGenerationError("OLLAMA_TIMEOUT") from exc
    except (TypeError, ValueError) as exc:
        raise RagGenerationError("RAG_OUTPUT_INVALID") from exc
    finally:
        # `_build_service` shares this coordinator with normal generation; it is
        # closed only during application shutdown.
        del coordinator


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/v1/rag/drafts/generate/stream")
async def stream_rag_draft(
    request: Request,
    body: RagDraftGenerationRequest,
    idempotency_key: str = Depends(rag_idempotency_key),
) -> StreamingResponse:
    """Stream validated generation phases without exposing partial legal text."""

    template, case_file = await _validate_generation_context(body)
    request_id = str(getattr(request.state, "request_id", ""))
    service, _coordinator = _build_service()
    queue: asyncio.Queue[tuple[str, dict[str, object]]] = asyncio.Queue()
    run_id: UUID | None = None
    active_ref: list[_ActiveRagRun | None] = [None]

    async def progress(phase: str, run: RagGenerationRun | None) -> None:
        nonlocal run_id
        if run is not None:
            run_id = run.id
            active = active_ref[0]
            if active is not None:
                _active_runs[run_id] = active
        await queue.put(
            (
                "progress",
                {
                    "request_id": request_id,
                    "rag_run_id": str(run_id) if run_id else None,
                    "phase": phase,
                },
            )
        )

    cancel_event = asyncio.Event()
    task = asyncio.create_task(
        service.generate(
            body,
            idempotency_key=idempotency_key,
            request_id=request_id,
            query_context=_query_context(template, case_file),
            progress_callback=progress,
            cancel_event=cancel_event,
            template_body=getattr(template, "body_template", None),
            target_document_type=_enum_value(
                getattr(template, "document_type", None), "disposicion"
            ),
        )
    )
    active = _ActiveRagRun(task=task, cancel_event=cancel_event)
    active_ref[0] = active

    def cleanup(_done: asyncio.Task[RagGenerationOutcome]) -> None:
        if run_id is not None and _active_runs.get(run_id) is active:
            _active_runs.pop(run_id, None)

    task.add_done_callback(cleanup)

    async def events() -> AsyncIterator[str]:
        nonlocal run_id
        yield _sse(
            "started",
            {"request_id": request_id, "rag_run_id": None},
        )
        try:
            while not task.done() or not queue.empty():
                try:
                    event, payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield _sse(event, payload)
                except TimeoutError:
                    yield ": heartbeat\n\n"
            try:
                outcome = task.result()
                yield _sse(
                    "complete",
                    {
                        "request_id": request_id,
                        "rag_run_id": str(outcome.run.id),
                        "result": _result_response(request_id, outcome).model_dump(
                            mode="json"
                        ),
                    },
                )
            except asyncio.CancelledError:
                yield _sse(
                    "cancelled",
                    {
                        "request_id": request_id,
                        "rag_run_id": str(run_id) if run_id else None,
                    },
                )
            except DomainError as exc:
                event = (
                    "cancelled"
                    if exc.code == "RAG_GENERATION_CANCELLED"
                    else "error"
                )
                yield _sse(
                    event,
                    {
                        "request_id": request_id,
                        "rag_run_id": str(run_id) if run_id else None,
                        "code": exc.code,
                        "message": exc.message,
                        "retryable": exc.status_code in {503, 504},
                    },
                )
            except Exception:
                yield _sse(
                    "error",
                    {
                        "request_id": request_id,
                        "rag_run_id": str(run_id) if run_id else None,
                        "code": "RAG_INTERNAL_ERROR",
                        "message": "La generación RAG no pudo completarse.",
                        "retryable": True,
                    },
                )
        except asyncio.CancelledError:
            raise
        finally:
            if run_id is not None and task.done():
                _active_runs.pop(run_id, None)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )


@router.delete("/api/v1/rag/runs/{run_id}")
async def cancel_rag_run(run_id: UUID, request: Request) -> dict[str, object]:
    active = _active_runs.get(run_id)
    if active is not None and not active.task.done():
        active.cancel_event.set()
        active.task.cancel()
        return {
            "request_id": str(getattr(request.state, "request_id", "")),
            "rag_run_id": str(run_id),
            "status": "cancellation_requested",
        }
    if settings.rag_profile.code == "imi_leg_06b":
        stored = await ImiRagAuditStore().get_run(run_id)
        run = stored[0] if stored is not None else None
    else:
        async with UnitOfWork() as uow:
            run = await uow.rag_runs.get(run_id)
    if run is None:
        raise RagRunNotFoundError()
    return {
        "request_id": str(getattr(request.state, "request_id", "")),
        "rag_run_id": str(run_id),
        "status": str(run.status),
    }


@router.get("/api/v1/rag/runs/{run_id}", response_model=RagRunResponse)
async def get_rag_run(run_id: UUID) -> RagRunResponse:
    sources: list[Any]
    if settings.rag_profile.code == "imi_leg_06b":
        stored = await ImiRagAuditStore().get_run(run_id)
        if stored is None:
            raise RagRunNotFoundError()
        run, sources = stored
    else:
        async with UnitOfWork() as uow:
            legacy_run = await uow.rag_runs.get(run_id)
            if legacy_run is None:
                raise RagRunNotFoundError()
            run = legacy_run
            sources = await uow.rag_sources.list_by_run(run_id)
    return RagRunResponse(
        id=run.id,
        draft_id=run.draft_id,
        case_file_id=run.case_file_id,
        template_id=run.template_id,
        status=str(run.status),
        models={
            "embedding": run.embedding_model,
            "dimensions": run.embedding_dimensions,
            "generation": run.generation_model,
        },
        versions={"prompt": run.prompt_version, "schema": run.schema_version},
        retrieval={"retrieved": run.retrieved_count, "selected": run.selected_count},
        durations_ms={
            "retrieval": run.retrieval_duration_ms,
            "generation": run.generation_duration_ms,
            "validation": run.validation_duration_ms,
            "total": run.total_duration_ms,
        },
        sources=[
            RagRunSourceResponse(
                citation_id=source.citation_id,
                document_id=source.document_id,
                chunk_id=source.chunk_id,
                rank=source.retrieval_rank,
                score=float(source.similarity_score),
                disposition=source.disposition,
            )
            for source in sources
        ],
        error_code=run.error_code,
        request_id=run.request_id,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )
