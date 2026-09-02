"""Template endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from legal_ai.adapters.database.imi_core import ImiCoreUnitOfWork
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.template_service import TemplateService
from legal_ai.config import settings
from legal_ai.schemas.errors import ErrorResponse
from legal_ai.schemas.pagination import PaginatedResponse
from legal_ai.schemas.template import (
    CreateTemplateRequest,
    TemplateResponse,
    UpdateTemplateRequest,
)

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


def _reject_legacy_write() -> None:
    """Prevent IMI requests from silently writing to the legacy database."""
    if settings.rag_profile.code == "imi_leg_06b":
        raise HTTPException(
            status_code=501,
            detail={
                "code": "IMI_CORE_WRITE_NOT_IMPLEMENTED",
                "message": (
                    "Las escrituras de plantillas de IMI requieren el repositorio "
                    "imi_leg_core."
                ),
            },
        )


@router.post(
    "",
    response_model=TemplateResponse,
    status_code=201,
    responses={
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_template(
    request: Request,
    body: CreateTemplateRequest,
) -> TemplateResponse:
    _reject_legacy_write()
    async with UnitOfWork() as uow:
        service = TemplateService(uow)
        template = await service.create_template(
            name=body.name,
            document_type=body.document_type,
            body_template=body.body_template,
            organ_emisor=body.organ_emisor,
            normativa=body.normativa,
            description=body.description,
            variables=body.variables,
        )
    return TemplateResponse.model_validate(template)


@router.get(
    "",
    response_model=PaginatedResponse[TemplateResponse],
    responses={422: {"model": ErrorResponse}},
)
async def list_templates(
    request: Request,
    document_type: str | None = Query(None),
    search: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[TemplateResponse]:
    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as uow:
            if uow.core is None:
                raise RuntimeError("IMI_CORE_UNAVAILABLE")
            items, total = await uow.core.list_templates(
                document_type=document_type,
                search=search,
                skip=skip,
                limit=limit,
            )
        return PaginatedResponse(
            page=skip // limit + 1,
            page_size=limit,
            total=total,
            items=[TemplateResponse.model_validate(t) for t in items],
        )
    async with UnitOfWork() as uow:
        service = TemplateService(uow)
        items, total = await service.list_templates(document_type, search, skip, limit)
    return PaginatedResponse(
        page=skip // limit + 1,
        page_size=limit,
        total=total,
        items=[TemplateResponse.model_validate(t) for t in items],
    )


@router.get(
    "/{template_id}",
    response_model=TemplateResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_template(
    request: Request,
    template_id: UUID,
) -> TemplateResponse:
    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as uow:
            if uow.core is None:
                raise RuntimeError("IMI_CORE_UNAVAILABLE")
            template = await uow.core.get_template(template_id)
        if template is None:
            from legal_ai.application.template_service import TemplateNotFoundError

            raise TemplateNotFoundError(str(template_id))
        return TemplateResponse.model_validate(template)
    async with UnitOfWork() as uow:
        service = TemplateService(uow)
        template = await service.get_template(str(template_id))
    return TemplateResponse.model_validate(template)


@router.patch(
    "/{template_id}",
    response_model=TemplateResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def update_template(
    request: Request,
    template_id: UUID,
    body: UpdateTemplateRequest,
) -> TemplateResponse:
    _reject_legacy_write()
    async with UnitOfWork() as uow:
        service = TemplateService(uow)
        template = await service.update_template(
            str(template_id),
            body_template=body.body_template,
            organ_emisor=body.organ_emisor,
            normativa=body.normativa,
            description=body.description,
            variables=body.variables,
        )
    return TemplateResponse.model_validate(template)


@router.post(
    "/{template_id}/deactivate",
    response_model=TemplateResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def deactivate_template(
    request: Request,
    template_id: UUID,
) -> TemplateResponse:
    _reject_legacy_write()
    async with UnitOfWork() as uow:
        service = TemplateService(uow)
        template = await service.deactivate_template(str(template_id))
    return TemplateResponse.model_validate(template)
