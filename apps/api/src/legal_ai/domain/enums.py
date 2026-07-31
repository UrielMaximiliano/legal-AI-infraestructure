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
