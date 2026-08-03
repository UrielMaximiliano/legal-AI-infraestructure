"""API exception handlers for domain errors."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from legal_ai.api.routes.generation import GenerationAttemptNotFoundError
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
from legal_ai.schemas.errors import ErrorResponse, ValidationErrorDetail


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

    if isinstance(
        exc,
        (
            CaseFileNotFoundError,
            DesignationCaseFileNotFoundError,
            DraftCaseFileNotFoundError,
        ),
    ):
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

    if isinstance(exc, (TemplateNotFoundError, DraftTemplateNotFoundError)):
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="DOCUMENT_TEMPLATE_NOT_FOUND",
                message="Plantilla no encontrada",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, DraftNotFoundError):
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="DRAFT_NOT_FOUND",
                message="Borrador no encontrado",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, DesignationNotFoundError):
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="DESIGNATION_DATA_NOT_FOUND",
                message="Datos de designación no encontrados",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, GenerationAttemptNotFoundError):
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="GENERATION_ATTEMPT_NOT_FOUND",
                message="Intento de generación no encontrado",
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

    if isinstance(exc, (ConcurrentModificationError, DraftConcurrentModificationError)):
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

    if isinstance(exc, TemplateNameConflictError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="DOCUMENT_TEMPLATE_NAME_EXISTS",
                message="Ya existe una plantilla con ese nombre y tipo",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, TemplateConflictError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="DOCUMENT_TEMPLATE_CONFLICT",
                message="La plantilla ha sido modificada por otro usuario",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, (TemplateInactiveError, DraftTemplateInactiveError)):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="DOCUMENT_TEMPLATE_INACTIVE",
                message="La plantilla está desactivada",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, DraftReadOnlyError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="DRAFT_READ_ONLY",
                message="El borrador está en estado de solo lectura",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, InvalidDraftTransitionError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="INVALID_DRAFT_TRANSITION",
                message=f"Transición no válida: {exc.from_status} → {exc.to_status}",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, DraftAlreadyApprovedError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="DRAFT_ALREADY_APPROVED",
                message="El borrador ya fue aprobado",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, CaseFileTypeIncompatibleError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="CASE_FILE_TYPE_INCOMPATIBLE",
                message="El tipo de expediente es incompatible con la operación",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, DesignationExistsError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="DESIGNATION_EXISTS",
                message="Ya existen datos de designación para este expediente",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, IdempotencyKeyMismatchError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="IDEMPOTENCY_KEY_MISMATCH",
                message="La clave de idempotencia existe pero con payload diferente",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, GenerationInProgressError):
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="GENERATION_IN_PROGRESS",
                message="Ya hay una generación en progreso para esta clave",
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

    if isinstance(exc, ContentTooLargeError):
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error_code="CONTENT_TOO_LARGE",
                message=f"El contenido excede el límite de {exc.limit} bytes",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, (MissingRequiredVariablesError, DesignationDataIncompleteError)):
        if isinstance(exc, MissingRequiredVariablesError):
            return JSONResponse(
                status_code=422,
                content=ErrorResponse(
                    error_code="MISSING_REQUIRED_VARIABLES",
                    message="Faltan variables requeridas por la plantilla",
                    errors=[
                        ValidationErrorDetail(
                            field=variable,
                            code="missing",
                            message="Variable requerida",
                        )
                        for variable in exc.missing
                    ],
                    request_id=request_id,
                ).model_dump(),
            )
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error_code="DESIGNATION_DATA_INCOMPLETE",
                message="Los datos de designación están incompletos",
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


async def service_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle Ollama and generation errors (502/503/504)."""
    request_id = getattr(request.state, "request_id", None)

    if isinstance(exc, OllamaUnavailableError):
        return JSONResponse(
            status_code=503,
            content=ErrorResponse(
                error_code="OLLAMA_UNAVAILABLE",
                message="Servicio Ollama no disponible",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, OllamaTimeoutError):
        return JSONResponse(
            status_code=504,
            content=ErrorResponse(
                error_code="OLLAMA_TIMEOUT",
                message="Timeout en la llamada a Ollama",
                request_id=request_id,
            ).model_dump(),
        )

    if isinstance(exc, (GenerationFailedError, OllamaError)):
        return JSONResponse(
            status_code=502,
            content=ErrorResponse(
                error_code="GENERATION_FAILED",
                message="La generación del documento falló",
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
    if isinstance(exc, ContextBuildFailedError):
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error_code="CONTEXT_BUILD_FAILED",
                message="No se pudo construir el contexto de generación",
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
