"""Aplicación FastAPI principal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from legal_ai.adapters.database.engine import dispose_engine
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.api.exceptions import (
    conflict_error_handler,
    domain_error_handler,
    generic_error_handler,
    not_found_error_handler,
    service_error_handler,
    validation_error_handler,
)
from legal_ai.api.middleware import RagSecurityMiddleware, ServiceTokenMiddleware
from legal_ai.api.router import router
from legal_ai.api.routes.generation import GenerationAttemptNotFoundError
from legal_ai.api.routes.rag import close_rag_coordinator
from legal_ai.application.case_file_service import (
    CaseFileArchivedError,
    CaseFileEmployeeInactiveError,
    CaseFileEmployeeNotFoundError,
    CaseFileNotFoundError,
    ConcurrentModificationError,
    InvalidStatusTransitionError,
)
from legal_ai.application.designation_service import (
    CaseFileNotFoundError as DesignationCaseFileNotFoundError,
)
from legal_ai.application.designation_service import (
    CaseFileTypeIncompatibleError,
    DesignationExistsError,
    DesignationNotFoundError,
)
from legal_ai.application.draft_service import (
    CaseFileNotFoundError as DraftCaseFileNotFoundError,
)
from legal_ai.application.draft_service import (
    ConcurrentModificationError as DraftConcurrentModificationError,
)
from legal_ai.application.draft_service import (
    ContentTooLargeError,
    DraftAlreadyApprovedError,
    DraftNotFoundError,
    DraftReadOnlyError,
    GenerationInProgressError,
    IdempotencyKeyMismatchError,
    InvalidDraftTransitionError,
)
from legal_ai.application.draft_service import (
    TemplateInactiveError as DraftTemplateInactiveError,
)
from legal_ai.application.draft_service import (
    TemplateNotFoundError as DraftTemplateNotFoundError,
)
from legal_ai.application.employee_service import (
    EmployeeDocumentConflictError,
    EmployeeNotFoundError,
    EmployeeNumberConflictError,
)
from legal_ai.application.generation_context import (
    ContextBuildFailedError,
    DesignationDataIncompleteError,
    MissingRequiredVariablesError,
)
from legal_ai.application.ollama_client import (
    GenerationFailedError,
    OllamaError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from legal_ai.application.template_service import (
    TemplateConflictError,
    TemplateInactiveError,
    TemplateNameConflictError,
    TemplateNotFoundError,
)
from legal_ai.config import settings
from legal_ai.domain.errors import DomainError
from legal_ai.observability.logging import setup_logging
from legal_ai.observability.request_context import RequestContextMiddleware
from legal_ai.schemas.errors import ErrorResponse, ValidationErrorDetail


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Gestión del lifespan de la aplicación."""
    setup_logging(settings.logging.level)
    try:
        async with UnitOfWork() as uow:
            await uow.rag_runs.close_orphaned()
        yield
    finally:
        await close_rag_coordinator()
        await dispose_engine()


app = FastAPI(
    title=settings.app.name,
    version=settings.app.version,
    lifespan=lifespan,
)

# RequestContextMiddleware remains outermost so rejected requests still receive a
# sanitized correlation id. ServiceTokenMiddleware validates the private BFF token
# when one is configured for API routes.
app.add_middleware(RagSecurityMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(RequestContextMiddleware)
app.include_router(router)

# Register exception handlers
app.add_exception_handler(EmployeeNotFoundError, not_found_error_handler)
app.add_exception_handler(CaseFileNotFoundError, not_found_error_handler)
app.add_exception_handler(DesignationCaseFileNotFoundError, not_found_error_handler)
app.add_exception_handler(DraftCaseFileNotFoundError, not_found_error_handler)
app.add_exception_handler(CaseFileEmployeeNotFoundError, not_found_error_handler)
app.add_exception_handler(TemplateNotFoundError, not_found_error_handler)
app.add_exception_handler(DraftTemplateNotFoundError, not_found_error_handler)
app.add_exception_handler(DraftNotFoundError, not_found_error_handler)
app.add_exception_handler(DesignationNotFoundError, not_found_error_handler)
app.add_exception_handler(GenerationAttemptNotFoundError, not_found_error_handler)
app.add_exception_handler(EmployeeNumberConflictError, conflict_error_handler)
app.add_exception_handler(EmployeeDocumentConflictError, conflict_error_handler)
app.add_exception_handler(CaseFileArchivedError, conflict_error_handler)
app.add_exception_handler(ConcurrentModificationError, conflict_error_handler)
app.add_exception_handler(DraftConcurrentModificationError, conflict_error_handler)
app.add_exception_handler(InvalidStatusTransitionError, conflict_error_handler)
app.add_exception_handler(TemplateNameConflictError, conflict_error_handler)
app.add_exception_handler(TemplateConflictError, conflict_error_handler)
app.add_exception_handler(TemplateInactiveError, conflict_error_handler)
app.add_exception_handler(DraftTemplateInactiveError, conflict_error_handler)
app.add_exception_handler(DraftReadOnlyError, conflict_error_handler)
app.add_exception_handler(InvalidDraftTransitionError, conflict_error_handler)
app.add_exception_handler(DraftAlreadyApprovedError, conflict_error_handler)
app.add_exception_handler(CaseFileTypeIncompatibleError, conflict_error_handler)
app.add_exception_handler(DesignationExistsError, conflict_error_handler)
app.add_exception_handler(IdempotencyKeyMismatchError, conflict_error_handler)
app.add_exception_handler(GenerationInProgressError, conflict_error_handler)
app.add_exception_handler(DomainError, domain_error_handler)
app.add_exception_handler(CaseFileEmployeeInactiveError, validation_error_handler)
app.add_exception_handler(ContentTooLargeError, validation_error_handler)
app.add_exception_handler(MissingRequiredVariablesError, validation_error_handler)
app.add_exception_handler(DesignationDataIncompleteError, validation_error_handler)
app.add_exception_handler(ContextBuildFailedError, generic_error_handler)
app.add_exception_handler(GenerationFailedError, service_error_handler)
app.add_exception_handler(OllamaUnavailableError, service_error_handler)
app.add_exception_handler(OllamaTimeoutError, service_error_handler)
app.add_exception_handler(OllamaError, service_error_handler)
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
