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
