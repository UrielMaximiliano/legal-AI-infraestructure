"""Schema de error estructurado."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


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
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: _utc_timestamp())
    error: PublicErrorEnvelope | None = None

    @model_validator(mode="after")
    def build_compatible_envelope(self) -> ErrorResponse:
        """Expose the 004 nested envelope while preserving 003 flat fields."""
        if self.error is None:
            self.error = PublicErrorEnvelope(
                code=self.error_code,
                message=self.message,
                details=self.details,
                request_id=self.request_id,
                timestamp=self.timestamp,
            )
        return self


class PublicErrorEnvelope(BaseModel):
    """Nested public error contract used by 004 and tolerated by 003 clients."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    timestamp: str


def _utc_timestamp() -> str:
    """Return a server-generated UTC RFC 3339 timestamp with ``Z`` suffix."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
