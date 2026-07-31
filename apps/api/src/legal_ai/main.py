"""Aplicación FastAPI principal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from legal_ai.api.exceptions import (
    conflict_error_handler,
    generic_error_handler,
    not_found_error_handler,
    validation_error_handler,
)
from legal_ai.api.router import router
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
from legal_ai.config import settings
from legal_ai.observability.logging import setup_logging
from legal_ai.observability.request_context import RequestContextMiddleware
from legal_ai.schemas.errors import ErrorResponse, ValidationErrorDetail


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Gestión del lifespan de la aplicación."""
    setup_logging(settings.logging.level)
    yield


app = FastAPI(
    title=settings.app.name,
    version=settings.app.version,
    lifespan=lifespan,
)

app.add_middleware(RequestContextMiddleware)
app.include_router(router)

# Register exception handlers
app.add_exception_handler(EmployeeNotFoundError, not_found_error_handler)
app.add_exception_handler(CaseFileNotFoundError, not_found_error_handler)
app.add_exception_handler(CaseFileEmployeeNotFoundError, not_found_error_handler)
app.add_exception_handler(EmployeeNumberConflictError, conflict_error_handler)
app.add_exception_handler(EmployeeDocumentConflictError, conflict_error_handler)
app.add_exception_handler(CaseFileArchivedError, conflict_error_handler)
app.add_exception_handler(ConcurrentModificationError, conflict_error_handler)
app.add_exception_handler(InvalidStatusTransitionError, conflict_error_handler)
app.add_exception_handler(CaseFileEmployeeInactiveError, validation_error_handler)
app.add_exception_handler(Exception, generic_error_handler)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle FastAPI validation errors (422) with uniform format."""
    request_id = getattr(request.state, "request_id", None)
    validation_errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"] if loc != "body")
        code = error["type"]
        message = error["msg"]
        validation_errors.append(
            ValidationErrorDetail(field=field or "body", code=code, message=message)
        )
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="La solicitud contiene datos inválidos",
            errors=validation_errors,
            request_id=request_id,
        ).model_dump(),
    )
