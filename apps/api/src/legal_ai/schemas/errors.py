"""Schema de error estructurado."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Respuesta de error estructurado."""

    error_code: str = Field(description="Código de error estable")
    message: str = Field(description="Mensaje técnico breve sin secretos")
    request_id: str | None = Field(default=None, description="UUID v4 de correlación")
