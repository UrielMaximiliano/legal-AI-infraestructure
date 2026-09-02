"""Draft endpoints."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from legal_ai.adapters.database.imi_core import ImiCoreUnitOfWork
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.api.dependencies import required_idempotency_key
from legal_ai.application.draft_service import DraftNotFoundError, DraftService
from legal_ai.application.finalization_service import FinalizationService
from legal_ai.application.preview_service import PreviewService
from legal_ai.application.structured_document_service import StructuredDocumentService
from legal_ai.config import settings
from legal_ai.domain.enums import GenerationStatus
from legal_ai.domain.errors import DraftDocumentNotFoundError
from legal_ai.schemas.document import (
    CreateManualDraftRequest,
    DraftDocumentResponse,
    LegalDocument,
    UpdateDraftDocumentRequest,
)
from legal_ai.schemas.draft import (
    DraftResponse,
    DraftTransitionResponse,
    EditDraftContentRequest,
    GenerateDraftRequest,
    RegenerateDraftRequest,
    TransitionDraftRequest,
)
from legal_ai.schemas.errors import ErrorResponse
from legal_ai.schemas.finalization import FinalizationResponse, FinalizeDraftRequest
from legal_ai.schemas.pagination import PaginatedResponse

router = APIRouter(tags=["drafts"])


def _normalize_document_value(value: Any) -> Any:
    """Make persisted corpus text safe for the strict editor contract."""
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, list):
        return [_normalize_document_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_document_value(item) for key, item in value.items()}
    return value


@router.post(
    "/api/v1/drafts/{draft_id}/finalize",
    response_model=FinalizationResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def finalize_draft(
    request: Request,
    response: Response,
    draft_id: UUID,
    body: FinalizeDraftRequest,
) -> FinalizationResponse:
    async with UnitOfWork() as uow:
        result = await FinalizationService(uow).finalize(
            draft_id,
            body.expected_version,
            body.finalized_by,
            body.finalization_notes,
            str(getattr(request.state, "request_id", "")),
            body.official_number,
            body.issued_on,
        )
    response.status_code = result.status_code
    if result.draft.finalized_at is None:
        raise RuntimeError("finalization invariant violated")
    return FinalizationResponse(
        draft_id=result.draft.id,
        draft_version=result.draft.version,
        finalized_by=result.draft.finalized_by or "",
        finalized_at=result.draft.finalized_at,
        finalization_notes=result.draft.finalization_notes,
        final_snapshot=result.snapshot,
        final_snapshot_sha256=result.sha256,
        official_number=(
            result.identifier.number
            if result.identifier is not None
            else body.official_number
        ),
        issued_on=(
            result.identifier.issued_on
            if result.identifier is not None
            else body.issued_on
        ),
    )


@router.get(
    "/api/v1/drafts",
    response_model=PaginatedResponse[DraftResponse],
    responses={422: {"model": ErrorResponse}},
)
async def list_all_drafts(
    request: Request,
    document_type: str | None = Query(None, min_length=1, max_length=50),
    query: str | None = Query(None, max_length=200),
    case_file_id: UUID | None = Query(None),  # noqa: B008
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[DraftResponse]:
    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as core_uow:
            items, total = await core_uow.core.list_drafts(
                page=page,
                page_size=page_size,
                query=query,
                document_type=document_type,
                case_file_id=case_file_id,
            ) if core_uow.core is not None else ([], 0)
        return PaginatedResponse(
            page=page,
            page_size=page_size,
            total=total,
            request_id=str(getattr(request.state, "request_id", "")),
            items=[DraftResponse.model_validate(item) for item in items],
        )

    async with UnitOfWork() as uow:
        items, total = await uow.drafts.list_all(
            query_text=query,
            document_type=document_type,
            case_file_id=case_file_id,
            status=None,
            skip=(page - 1) * page_size,
            limit=page_size,
        )
    return PaginatedResponse(
        page=page,
        page_size=page_size,
        total=total,
        request_id=str(getattr(request.state, "request_id", "")),
        items=[DraftResponse.model_validate(item) for item in items],
    )


@router.post(
    "/api/v1/drafts",
    response_model=DraftResponse,
    status_code=201,
    responses={200: {"model": DraftResponse}, 409: {"model": ErrorResponse}},
)
async def create_manual_draft(
    request: Request,
    response: Response,
    body: CreateManualDraftRequest,
    idempotency_key: str = Depends(required_idempotency_key),
    actor: str | None = Header(None, alias="X-Actor"),
) -> DraftResponse:
    payload_hash = sha256(
        json.dumps(body.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as core_uow:
            draft = await core_uow.core.create_manual_draft(
                template_id=body.template_id,
                case_file_id=body.case_file_id,
                variables=body.variables,
                document=body.document,
                actor=actor or "imi-leg",
                idempotency_key=idempotency_key,
                request_hash=payload_hash,
                request_id=str(getattr(request.state, "request_id", "")),
            ) if core_uow.core is not None else None
        if draft is None:
            raise DraftDocumentNotFoundError(
                details={"template_id": str(body.template_id)}
            )
        response.status_code = 201
        return DraftResponse.model_validate(draft)

    async with UnitOfWork() as uow:
        existing = await uow.drafts.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.context_snapshot.get("manual_request_hash") != payload_hash:
                from legal_ai.domain.errors import IdempotencyConflictError

                raise IdempotencyConflictError()
            response.status_code = 200
            return DraftResponse.model_validate(existing)
        context_actor = actor or "imi-leg"
        draft = await StructuredDocumentService(uow).create_manual(
            template_id=body.template_id,
            case_file_id=body.case_file_id,
            variables=body.variables,
            document=body.document,
            actor=context_actor,
            idempotency_key=idempotency_key,
            request_hash=payload_hash,
        )
    return DraftResponse.model_validate(draft)


@router.get(
    "/api/v1/drafts/{draft_id}/document",
    response_model=DraftDocumentResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def get_draft_document(draft_id: UUID) -> DraftDocumentResponse:
    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as core_uow:
            draft = (
                await core_uow.core.get_draft(draft_id)
                if core_uow.core is not None
                else None
            )
        if draft is None or draft.document is None:
            raise DraftDocumentNotFoundError(details={"draft_id": str(draft_id)})
        try:
            payload = _normalize_document_value(dict(draft.document))
            payload.setdefault("document_type", draft.document_type)
            payload.setdefault("locale", "es-AR")
            payload.setdefault("institutional_header", "IMI")
            document = LegalDocument.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise DraftDocumentNotFoundError(
                details={"draft_id": str(draft_id)}
            ) from exc
        return DraftDocumentResponse(
            draft_id=draft.id,
            draft_version=draft.version,
            document=document,
            source=str(draft.context_snapshot.get("source_code", "AI")),
            document_hash=draft.context_hash,
            updated_at=draft.updated_at,
        )

    async with UnitOfWork() as uow:
        draft, document, version = await StructuredDocumentService(uow).get(draft_id)
    return DraftDocumentResponse(
        draft_id=draft.id,
        draft_version=draft.version,
        document=document,
        source=version.source,
        document_hash=version.document_hash,
        updated_at=draft.updated_at,
    )


@router.patch(
    "/api/v1/drafts/{draft_id}/document",
    response_model=DraftDocumentResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def update_draft_document(
    request: Request,
    draft_id: UUID,
    body: UpdateDraftDocumentRequest,
    actor: str | None = Header(None, alias="X-Actor"),
) -> DraftDocumentResponse:
    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as core_uow:
            draft = (
                await core_uow.core.update_document(
                    draft_id=draft_id,
                    expected_version=body.expected_version,
                    document=body.document,
                    actor=actor or "imi-leg",
                )
                if core_uow.core is not None
                else None
            )
        if draft is None:
            raise DraftDocumentNotFoundError(details={"draft_id": str(draft_id)})
        return DraftDocumentResponse(
            draft_id=draft.id,
            draft_version=draft.version,
            document=body.document,
            source="EDITED",
            document_hash=draft.context_hash,
            updated_at=draft.updated_at,
        )

    async with UnitOfWork() as uow:
        draft, document, version = await StructuredDocumentService(uow).update(
            draft_id=draft_id,
            expected_version=body.expected_version,
            document=body.document,
            actor=actor or "imi-leg",
        )
    return DraftDocumentResponse(
        draft_id=draft.id,
        draft_version=draft.version,
        document=document,
        source=version.source,
        document_hash=version.document_hash,
        updated_at=draft.updated_at,
    )


@router.get(
    "/api/v1/drafts/{draft_id}/preview",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def preview_draft(
    request: Request,
    draft_id: UUID,
    draft_version: int = Query(..., gt=0),
) -> Response:
    async with UnitOfWork() as uow:
        result = await PreviewService(uow).preview(draft_id, draft_version)
    return Response(
        content=result.html,
        media_type="text/html",
        headers={
            "ETag": f'"sha256:{result.sha256}"',
            "Cache-Control": "no-store",
            "X-Request-ID": str(getattr(request.state, "request_id", "")),
        },
    )


@router.post(
    "/api/v1/drafts/generate",
    response_model=DraftResponse,
    status_code=201,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def generate_draft(
    request: Request,
    response: Response,
    body: GenerateDraftRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> DraftResponse:
    async with UnitOfWork() as uow:
        service = DraftService(uow)
        cached = None
        if idempotency_key:
            cached = await uow.generation_attempts.get_by_idempotency_key(
                idempotency_key
            )
        draft = await service.generate_draft(
            template_id=str(body.template_id),
            case_file_id=str(body.case_file_id),
            variables=body.variables,
            idempotency_key=idempotency_key,
        )
        if cached and cached.status == GenerationStatus.COMPLETED:
            response.status_code = 200
    return DraftResponse.model_validate(draft)


@router.get(
    "/api/v1/case-files/{case_file_id}/drafts",
    response_model=PaginatedResponse[DraftResponse],
    responses={
        404: {"model": ErrorResponse},
    },
)
async def list_drafts(
    request: Request,
    case_file_id: UUID,
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[DraftResponse]:
    async with UnitOfWork() as uow:
        service = DraftService(uow)
        items, total = await service.list_drafts(str(case_file_id), status, skip, limit)
    return PaginatedResponse(
        page=skip // limit + 1,
        page_size=limit,
        total=total,
        items=[DraftResponse.model_validate(d) for d in items],
    )


@router.get(
    "/api/v1/drafts/{draft_id}",
    response_model=DraftResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_draft(
    request: Request,
    draft_id: UUID,
) -> DraftResponse:
    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as core_uow:
            draft = (
                await core_uow.core.get_draft(draft_id)
                if core_uow.core is not None
                else None
            )
        if draft is None:
            raise DraftNotFoundError(str(draft_id))
        return DraftResponse.model_validate(draft)

    async with UnitOfWork() as uow:
        service = DraftService(uow)
        draft = await service.get_draft(str(draft_id))
    return DraftResponse.model_validate(draft)


@router.patch(
    "/api/v1/drafts/{draft_id}/content",
    response_model=DraftResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def edit_draft_content(
    request: Request,
    draft_id: UUID,
    body: EditDraftContentRequest,
) -> DraftResponse:
    async with UnitOfWork() as uow:
        service = DraftService(uow)
        draft = await service.edit_content(
            str(draft_id), body.content, body.expected_version
        )
    return DraftResponse.model_validate(draft)


@router.post(
    "/api/v1/drafts/{draft_id}/transitions",
    response_model=DraftResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def transition_draft(
    request: Request,
    draft_id: UUID,
    body: TransitionDraftRequest,
) -> DraftResponse:
    async with UnitOfWork() as uow:
        service = DraftService(uow)
        draft = await service.transition_draft(
            str(draft_id), body.action, body.expected_version, body.observations
        )
    return DraftResponse.model_validate(draft)


@router.post(
    "/api/v1/drafts/{draft_id}/regenerate",
    response_model=DraftResponse,
    status_code=201,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def regenerate_draft(
    request: Request,
    draft_id: UUID,
    body: RegenerateDraftRequest,
) -> DraftResponse:
    async with UnitOfWork() as uow:
        service = DraftService(uow)
        draft = await service.regenerate_draft(
            str(draft_id), body.expected_version, body.observations
        )
    return DraftResponse.model_validate(draft)


@router.get(
    "/api/v1/drafts/{draft_id}/history",
    response_model=list[DraftTransitionResponse],
    responses={
        404: {"model": ErrorResponse},
    },
)
async def get_draft_history(
    request: Request,
    draft_id: UUID,
) -> list[DraftTransitionResponse]:
    async with UnitOfWork() as uow:
        service = DraftService(uow)
        transitions = await service.get_history(str(draft_id))
    return [DraftTransitionResponse.model_validate(t) for t in transitions]
