"""Draft endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.draft_service import DraftService
from legal_ai.domain.enums import GenerationStatus
from legal_ai.schemas.draft import (
    DraftResponse,
    DraftTransitionResponse,
    EditDraftContentRequest,
    GenerateDraftRequest,
    RegenerateDraftRequest,
    TransitionDraftRequest,
)
from legal_ai.schemas.errors import ErrorResponse
from legal_ai.schemas.pagination import PaginatedResponse

router = APIRouter(tags=["drafts"])


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
