"""Framework-independent domain errors for 004."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Stable public error metadata without framework or library details."""

    code = "DATABASE_ERROR"
    status_code = 500
    default_message = "La operación no pudo completarse"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class ReviewNotFoundError(DomainError):
    code = "REVIEW_NOT_FOUND"
    status_code = 404
    default_message = "La revisión solicitada no existe"


class CommentNotFoundError(DomainError):
    code = "COMMENT_NOT_FOUND"
    status_code = 404
    default_message = "El comentario solicitado no existe"


class InvalidReviewTransitionError(DomainError):
    code = "INVALID_REVIEW_TRANSITION"
    status_code = 409
    default_message = "La transición de revisión no está permitida"


class ReviewVersionMismatchError(DomainError):
    code = "REVIEW_VERSION_MISMATCH"
    status_code = 409
    default_message = "La revisión fue modificada por otro usuario"


class OpenBlockingCommentsError(DomainError):
    code = "OPEN_BLOCKING_COMMENTS"
    status_code = 409
    default_message = "La revisión tiene comentarios bloqueantes abiertos"


class HumanReviewRequiredError(DomainError):
    code = "HUMAN_REVIEW_REQUIRED"
    status_code = 422
    default_message = "Se requiere confirmación de revisión humana"


class MissingReviewReasonError(DomainError):
    code = "MISSING_REVIEW_REASON"
    status_code = 422
    default_message = "El motivo de solicitud de cambios es obligatorio"


class AnchorVersionMismatchError(DomainError):
    code = "ANCHOR_VERSION_MISMATCH"
    status_code = 422
    default_message = "El anclaje no coincide con la versión revisada"


class ReviewOperationInProgressError(DomainError):
    code = "REVIEW_OPERATION_IN_PROGRESS"
    status_code = 409
    default_message = "La operación de revisión ya está en progreso"


class IdempotencyConflictError(DomainError):
    code = "IDEMPOTENCY_CONFLICT"
    status_code = 409
    default_message = "La clave de idempotencia ya fue usada con otro payload"


class IdempotencyKeyRequiredError(DomainError):
    code = "IDEMPOTENCY_KEY_REQUIRED"
    status_code = 400
    default_message = "Idempotency-Key es obligatorio"


class DraftNotFound004Error(DomainError):
    code = "DRAFT_NOT_FOUND"
    status_code = 404
    default_message = "El borrador solicitado no existe"


class DraftNotApprovedError(DomainError):
    code = "DRAFT_NOT_APPROVED"
    status_code = 409
    default_message = "El borrador no está aprobado"


class InvalidFinalizationError(DomainError):
    code = "INVALID_FINALIZATION"
    status_code = 422
    default_message = "Los datos de finalización no son válidos"


class DraftAlreadyFinalizedError(DomainError):
    code = "DRAFT_ALREADY_FINALIZED"
    status_code = 409
    default_message = "El borrador ya fue finalizado"


class ConcurrentModification004Error(DomainError):
    code = "CONCURRENT_MODIFICATION"
    status_code = 409
    default_message = "El recurso fue modificado por otro usuario"


class ContentTooLarge004Error(DomainError):
    code = "CONTENT_TOO_LARGE"
    status_code = 422

    def __init__(self, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(details={"size": size, "limit": limit})
    default_message = "El contenido excede el límite permitido"


class ExportSizeExceededError(DomainError):
    """A preview or artifact exceeded its configured byte limit."""

    code = "EXPORT_SIZE_EXCEEDED"
    status_code = 413
    default_message = "El artefacto excede el limite de tamano permitido"

    def __init__(self, size: int, limit: int) -> None:
        super().__init__(details={"size_bytes": size, "limit_bytes": limit})


class InvalidArtifactError(DomainError):
    """An artifact failed a public structural or MIME validation."""

    code = "MIME_VALIDATION_FAILED"
    status_code = 422
    default_message = "El artefacto no cumple el formato esperado"


class HashValidationError(DomainError):
    """An artifact digest does not match its persisted digest."""

    code = "HASH_VALIDATION_FAILED"
    status_code = 409
    default_message = "La integridad del artefacto no pudo verificarse"


class PathValidationError(DomainError):
    """A storage path is invalid or escapes the configured root."""

    code = "PATH_VALIDATION_FAILED"
    status_code = 500
    default_message = "La ruta del artefacto no es segura"


class FilesystemError(DomainError):
    """A local storage operation failed without exposing its path."""

    code = "FILESYSTEM_ERROR"
    status_code = 500
    default_message = "No se pudo completar la operacion de almacenamiento"


class GenerationTimeoutError(DomainError):
    """A renderer child process exceeded its deadline."""

    code = "GENERATION_TIMEOUT"
    status_code = 504
    default_message = "La generacion excedio el tiempo maximo permitido"


class RendererExecutionError(DomainError):
    """A renderer child failed with a sanitized error."""

    code = "EXPORT_GENERATION_FAILED"
    status_code = 500
    default_message = "La generacion del artefacto fallo"


class ValidationDomainError(DomainError):
    code = "VALIDATION_ERROR"
    status_code = 422


class DraftNotFinalizedError(DomainError):
    code = "DRAFT_NOT_FINALIZED"
    status_code = 409
    default_message = "El borrador no está finalizado"


class ExportNotFoundError(DomainError):
    code = "EXPORT_NOT_FOUND"
    status_code = 404
    default_message = "La exportación solicitada no existe"


class ExportFormatUnsupportedError(DomainError):
    code = "EXPORT_FORMAT_UNSUPPORTED"
    status_code = 422
    default_message = "El formato de exportación no está soportado"


class ExportInProgressError(DomainError):
    code = "EXPORT_IN_PROGRESS"
    status_code = 409
    default_message = "La exportación ya está en progreso"


class ActiveGenerationExistsError(DomainError):
    code = "ACTIVE_GENERATION_EXISTS"
    status_code = 409
    default_message = "Ya existe una generación activa para el formato"


class ExportAlreadyExistsError(DomainError):
    code = "EXPORT_ALREADY_EXISTS"
    status_code = 409
    default_message = "La exportación ya existe"


class ExportFileNotFoundError(DomainError):
    code = "EXPORT_FILE_NOT_FOUND"
    status_code = 410
    default_message = "El archivo exportado ya no está disponible"


class ExportFileCorruptedError(DomainError):
    code = "EXPORT_FILE_CORRUPTED"
    status_code = 409
    default_message = "El archivo exportado no superó la validación de integridad"


class InvalidExportTransitionError(DomainError):
    code = "INVALID_EXPORT_TRANSITION"
    status_code = 409
    default_message = "La transición de exportación no está permitida"


class ExportVersionMismatchError(DomainError):
    """The requested regeneration version is no longer current."""

    code = "EXPORT_VERSION_MISMATCH"
    status_code = 409
    default_message = "La version de exportacion ya no es la actual"


class CleanupConflictError(DomainError):
    """A reconciliation run id was reused with a different request."""

    code = "CLEANUP_CONFLICT"
    status_code = 409
    default_message = "El run_id de reconciliacion ya fue usado con otros filtros"


class RangeNotSupportedError(DomainError):
    code = "RANGE_NOT_SUPPORTED"
    status_code = 416
    default_message = "Las solicitudes Range no están soportadas"
