"""API exception handlers for domain errors."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from legal_ai.application.case_file_service import (
    CaseFileArchivedError,
    CaseFileEmployeeInactiveError,
    CaseFileEmployeeNotFoundError,
    CaseFileNotFoundError,
    ConcurrentModificationError,
    InvalidStatusTransitionError,
)
from legal_ai.application.employee_service import (
    EmployeeDocumentConflictError,
    EmployeeNotFoundError,
    EmployeeNumberConflictError,
)
from legal_ai.schemas.errors import ErrorResponse


async def not_found_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle not found errors (404)."""
    request_id = getattr(request.state, "request_id", None)

    if isinstance(exc, EmployeeNotFoundError):
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="EMPLOYEE_NOT_FOUND",
                message="El empleado solicitado no existe",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, CaseFileNotFoundError):
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="CASE_FILE_NOT_FOUND",
                message="El expediente solicitado no existe",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, CaseFileEmployeeNotFoundError):
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="EMPLOYEE_NOT_FOUND",
                message="El empleado asociado no existe",
                request_id=request_id,
            ).model_dump(),
        )

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="DATABASE_ERROR",
            message="Error interno del servidor",
            request_id=request_id,
        ).model_dump(),
    )


async def conflict_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle conflict errors (409)."""
    request_id = getattr(request.state, "request_id", None)

    if isinstance(exc, EmployeeNumberConflictError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="EMPLOYEE_NUMBER_CONFLICT",
                message="El número de legajo ya existe",
                field="employee_number",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, EmployeeDocumentConflictError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="EMPLOYEE_DOCUMENT_CONFLICT",
                message="El documento ya existe",
                field=exc.field,
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, CaseFileArchivedError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="CASE_FILE_ARCHIVED",
                message="El expediente está archivado y no puede modificarse",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, ConcurrentModificationError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="CONCURRENT_MODIFICATION",
                message="El recurso ha sido modificado por otro usuario",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, InvalidStatusTransitionError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="INVALID_STATUS_TRANSITION",
                message=(
                    "Transición de estado no permitida: "
                    f"{exc.from_status} → {exc.to_status}"
                ),
                request_id=request_id,
            ).model_dump(),
        )

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="DATABASE_ERROR",
            message="Error interno del servidor",
            request_id=request_id,
        ).model_dump(),
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle validation errors (422)."""
    request_id = getattr(request.state, "request_id", None)

    if isinstance(exc, CaseFileEmployeeInactiveError):
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error_code="EMPLOYEE_INACTIVE",
                message=(
                    "El empleado está inactivo y no puede recibir nuevos expedientes"
                ),
                request_id=request_id,
            ).model_dump(),
        )

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="DATABASE_ERROR",
            message="Error interno del servidor",
            request_id=request_id,
        ).model_dump(),
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle generic errors (500)."""
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="DATABASE_ERROR",
            message="Error interno del servidor",
            request_id=request_id,
        ).model_dump(),
    )
