"""Employee API endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.employee_service import EmployeeService
from legal_ai.schemas.employee import (
    CreateEmployeeRequest,
    EmployeeResponse,
    UpdateEmployeeRequest,
)
from legal_ai.schemas.pagination import PaginatedResponse

router = APIRouter(prefix="/api/v1/employees", tags=["employees"])


def _to_response(employee: Any) -> EmployeeResponse:
    """Convert domain employee to response schema."""
    return EmployeeResponse(
        id=employee.id,
        employee_number=employee.employee_number,
        first_name=employee.first_name,
        last_name=employee.last_name,
        document_type=employee.document_type,
        document_number=employee.document_number,
        cuil=employee.cuil,
        email=employee.email,
        phone=employee.phone,
        position=employee.position,
        department=employee.department,
        active=employee.active,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
    )


@router.post("/", response_model=EmployeeResponse, status_code=201)
async def create_employee(
    request: Request,
    body: CreateEmployeeRequest,
) -> EmployeeResponse:
    """Create a new employee."""
    async with UnitOfWork() as uow:
        service = EmployeeService(uow)
        employee = await service.create(
            employee_number=body.employee_number,
            first_name=body.first_name,
            last_name=body.last_name,
            document_type=body.document_type,
            document_number=body.document_number,
            cuil=body.cuil,
            email=body.email,
            phone=body.phone,
            position=body.position,
            department=body.department,
        )
        return _to_response(employee)


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    request: Request,
    employee_id: uuid.UUID,
) -> EmployeeResponse:
    """Get employee by ID."""
    async with UnitOfWork() as uow:
        service = EmployeeService(uow)
        employee = await service.get_by_id(employee_id)
        return _to_response(employee)


@router.get("/", response_model=PaginatedResponse[EmployeeResponse])
async def list_employees(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    query: str | None = None,
    active: bool | None = None,
    department: str | None = None,
) -> PaginatedResponse[EmployeeResponse]:
    """List employees with pagination and filters."""
    async with UnitOfWork() as uow:
        service = EmployeeService(uow)
        employees, total = await service.list(
            page=page,
            page_size=page_size,
            query=query,
            active=active,
            department=department,
        )
        return PaginatedResponse(
            page=page,
            page_size=page_size,
            total=total,
            items=[_to_response(e) for e in employees],
        )


@router.patch("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    request: Request,
    employee_id: uuid.UUID,
    body: UpdateEmployeeRequest,
) -> EmployeeResponse:
    """Partial update of employee fields."""
    async with UnitOfWork() as uow:
        service = EmployeeService(uow)
        employee = await service.update(
            employee_id=employee_id,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            phone=body.phone,
            position=body.position,
            department=body.department,
        )
        return _to_response(employee)


@router.post("/{employee_id}/deactivate", response_model=EmployeeResponse)
async def deactivate_employee(
    request: Request,
    employee_id: uuid.UUID,
) -> EmployeeResponse:
    """Deactivate employee (idempotent)."""
    async with UnitOfWork() as uow:
        service = EmployeeService(uow)
        employee = await service.deactivate(employee_id)
        return _to_response(employee)
