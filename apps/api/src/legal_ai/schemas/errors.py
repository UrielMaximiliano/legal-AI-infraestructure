"""Schema de error estructurado."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ValidationErrorDetail(BaseModel):
    """Detalle de error de validación."""

    field: str
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Respuesta de error estructurado."""

    error_code: str = Field(description="Código de error estable")
    message: str = Field(description="Mensaje técnico breve sin secretos")
    field: str | None = Field(default=None, description="Campo en conflicto")
    errors: list[ValidationErrorDetail] | None = Field(
        default=None, description="Lista de errores (solo VALIDATION_ERROR)"
    )
    request_id: str | None = Field(default=None, description="UUID v4 de correlación")
