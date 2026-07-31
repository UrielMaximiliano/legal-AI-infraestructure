"""Case file API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.case_file_service import CaseFileService
from legal_ai.schemas.case_file import (
    CaseFileResponse,
    CreateCaseFileRequest,
    HistoryItem,
    HistoryResponse,
    TransitionRequest,
    UpdateCaseFileRequest,
)
from legal_ai.schemas.pagination import PaginatedResponse

router = APIRouter(prefix="/api/v1/case-files", tags=["case-files"])


def _to_response(case_file: Any) -> CaseFileResponse:
    """Convert domain case file to response schema."""
    return CaseFileResponse(
        id=case_file.id,
        case_number=case_file.case_number,
        employee_id=case_file.employee_id,
        title=case_file.title,
        description=case_file.description,
        case_type=case_file.case_type,
        status=case_file.status,
        version=case_file.version,
        opened_at=case_file.opened_at,
        created_at=case_file.created_at,
        updated_at=case_file.updated_at,
        closed_at=case_file.closed_at,
    )


def _to_history_response(history: list[Any]) -> HistoryResponse:
    """Convert domain history to response schema."""
    items = [
        HistoryItem(
            id=h.id,
            case_file_id=h.case_file_id,
            from_status=h.from_status,
            to_status=h.to_status,
            changed_at=h.changed_at,
            changed_by=h.changed_by,
            reason=h.reason,
            request_id=h.request_id,
        )
        for h in history
    ]
    return HistoryResponse(items=items)


@router.post("/", response_model=CaseFileResponse, status_code=201)
async def create_case_file(
    request: Request,
    body: CreateCaseFileRequest,
) -> CaseFileResponse:
    """Create a new case file."""
    request_id = getattr(request.state, "request_id", None)
    async with UnitOfWork() as uow:
        service = CaseFileService(uow)
        case_file = await service.create(
            employee_id=body.employee_id,
            title=body.title,
            case_type=body.case_type,
            description=body.description,
            request_id=request_id,
        )
        return _to_response(case_file)


@router.get("/{case_file_id}", response_model=CaseFileResponse)
async def get_case_file(
    request: Request,
    case_file_id: uuid.UUID,
) -> CaseFileResponse:
    """Get case file by ID."""
    async with UnitOfWork() as uow:
        service = CaseFileService(uow)
        case_file = await service.get_by_id(case_file_id)
        return _to_response(case_file)


@router.get("/", response_model=PaginatedResponse[CaseFileResponse])
async def list_case_files(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    query: str | None = None,
    employee_id: uuid.UUID | None = None,
    status: str | None = None,
    case_type: str | None = None,
    opened_from: datetime | None = None,
    opened_to: datetime | None = None,
) -> PaginatedResponse[CaseFileResponse]:
    """List case files with pagination and filters."""
    async with UnitOfWork() as uow:
        service = CaseFileService(uow)
        case_files, total = await service.list(
            page=page,
            page_size=page_size,
            query=query,
            employee_id=employee_id,
            status=status,
            case_type=case_type,
            opened_from=opened_from,
            opened_to=opened_to,
        )
        return PaginatedResponse(
            page=page,
            page_size=page_size,
            total=total,
            items=[_to_response(cf) for cf in case_files],
        )


@router.patch("/{case_file_id}", response_model=CaseFileResponse)
async def update_case_file(
    request: Request,
    case_file_id: uuid.UUID,
    body: UpdateCaseFileRequest,
) -> CaseFileResponse:
    """Partial update of case file fields with optimistic locking."""
    async with UnitOfWork() as uow:
        service = CaseFileService(uow)
        case_file = await service.update(
            case_file_id=case_file_id,
            title=body.title,
            description=body.description,
            expected_version=body.expected_version,
        )
        return _to_response(case_file)


@router.post(
    "/{case_file_id}/transitions",
    response_model=CaseFileResponse,
)
async def transition_case_file(
    request: Request,
    case_file_id: uuid.UUID,
    body: TransitionRequest,
) -> CaseFileResponse:
    """Execute a state transition on a case file."""
    request_id = getattr(request.state, "request_id", None)
    async with UnitOfWork() as uow:
        service = CaseFileService(uow)
        case_file = await service.transition(
            case_file_id=case_file_id,
            status=body.status,
            expected_version=body.expected_version,
            changed_by=body.changed_by,
            reason=body.reason,
            request_id=request_id,
        )
        return _to_response(case_file)


@router.get("/{case_file_id}/history", response_model=HistoryResponse)
async def get_case_file_history(
    request: Request,
    case_file_id: uuid.UUID,
) -> HistoryResponse:
    """Get case file history."""
    async with UnitOfWork() as uow:
        service = CaseFileService(uow)
        history = await service.get_history(case_file_id)
        return _to_history_response(history)
