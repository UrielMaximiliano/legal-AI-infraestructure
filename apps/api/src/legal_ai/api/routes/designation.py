"""Designation endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.designation_service import DesignationService
from legal_ai.schemas.designation import (
    CreateDesignationDataRequest,
    DesignationDataResponse,
)
from legal_ai.schemas.errors import ErrorResponse

router = APIRouter(tags=["designation"])


@router.post(
    "/api/v1/case-files/{case_file_id}/designation",
    response_model=DesignationDataResponse,
    status_code=201,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_designation(
    request: Request,
    case_file_id: UUID,
    body: CreateDesignationDataRequest,
) -> DesignationDataResponse:
    async with UnitOfWork() as uow:
        service = DesignationService(uow)
        designation = await service.create_designation(
            case_file_id=str(case_file_id),
            position_name=body.position_name,
            organizational_unit=body.organizational_unit,
            start_date=str(body.start_date) if body.start_date else None,
            legal_basis=body.legal_basis,
            appointing_authority=body.appointing_authority,
            salary_category=body.salary_category,
            work_schedule=body.work_schedule,
            observations=body.observations,
        )
    return DesignationDataResponse.model_validate(designation)


@router.get(
    "/api/v1/case-files/{case_file_id}/designation",
    response_model=DesignationDataResponse,
    responses={
        404: {"model": ErrorResponse},
    },
)
async def get_designation(
    request: Request,
    case_file_id: UUID,
) -> DesignationDataResponse:
    async with UnitOfWork() as uow:
        service = DesignationService(uow)
        designation = await service.get_designation(str(case_file_id))
    return DesignationDataResponse.model_validate(designation)


@router.put(
    "/api/v1/case-files/{case_file_id}/designation",
    response_model=DesignationDataResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def update_designation(
    request: Request,
    case_file_id: UUID,
    body: CreateDesignationDataRequest,
) -> DesignationDataResponse:
    async with UnitOfWork() as uow:
        service = DesignationService(uow)
        designation = await service.update_designation(
            case_file_id=str(case_file_id),
            position_name=body.position_name,
            organizational_unit=body.organizational_unit,
            start_date=str(body.start_date) if body.start_date else None,
            legal_basis=body.legal_basis,
            appointing_authority=body.appointing_authority,
            salary_category=body.salary_category,
            work_schedule=body.work_schedule,
            observations=body.observations,
        )
    return DesignationDataResponse.model_validate(designation)
