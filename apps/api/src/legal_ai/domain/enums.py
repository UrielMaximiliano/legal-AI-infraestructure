"""Domain enums for the legal-AI system."""

from enum import StrEnum


class DocumentType(StrEnum):
    """Tipos de documento permitidos."""

    DNI = "dni"
    LC = "lc"
    LE = "le"
    CI = "ci"
    PASSPORT = "pasaporte"


class CaseStatus(StrEnum):
    """Estados del expediente administrativo."""

    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    IN_PROCESS = "in_process"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class CaseType(StrEnum):
    """Tipos de expediente."""

    DESIGNACION = "designacion"
    LICENCIA = "licencia"
    RENUNCIA = "renuncia"
    CONTRATACION = "contratacion"
    OTRO = "otro"


class TemplateDocumentType(StrEnum):
    """Tipos de documento para plantillas."""

    RESOLUCION = "resolucion"
    INFORME = "informe"
    OFICIO = "oficio"
    SOLICITUD = "solicitud"
    ACUERDO = "acuerdo"
    OTROS = "otros"


class DraftStatus(StrEnum):
    """Estados del borrador de documento."""

    GENERADO = "generado"
    EN_REVISION = "en_revision"
    APROBADO = "aprobado"
    RECHAZADO = "rechazado"
    SUPERSEDED = "superseded"


class TransitionAction(StrEnum):
    """Acciones de transición de borrador."""

    SEND_TO_REVIEW = "send_to_review"
    APPROVE = "approve"
    REJECT = "reject"
    EDIT_CONTENT = "edit_content"


class GenerationStatus(StrEnum):
    """Estados de intento de generación."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    """Estados de una revisión humana versionada."""

    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"


class CommentSeverity(StrEnum):
    """Severidad de un comentario de revisión."""

    INFO = "INFO"
    SUGGESTION = "SUGGESTION"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class CommentStatus(StrEnum):
    """Estado no destructivo de un comentario."""

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ExportFormat(StrEnum):
    """Formatos persistibles de 004; HTML no es un artefacto persistido."""

    DOCX = "DOCX"
    PDF = "PDF"


class ExportStatus(StrEnum):
    """Estados del pipeline de artefactos."""

    PENDING = "PENDING"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


DocumentExportStatus = ExportStatus


class ExportAttemptStatus(StrEnum):
    """Estados de cada intento de procesamiento."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ReviewOperationStatus(StrEnum):
    """Estados de una solicitud idempotente de revisión."""

    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
