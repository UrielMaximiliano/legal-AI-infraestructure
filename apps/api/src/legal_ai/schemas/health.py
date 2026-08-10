"""Schemas Pydantic para los endpoints de health check."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthLiveResponse(BaseModel):
    """Respuesta del endpoint /health/live."""

    status: str = Field(default="ok", description="Siempre 'ok'")
    service: str = Field(description="Nombre del servicio")
    version: str = Field(description="Versión de la aplicación")
    request_id: str = Field(description="UUID v4 de correlación")


class DependencyHealthSchema(BaseModel):
    """Estado de una dependencia individual."""

    status: str = Field(description="Estado individual")
    latency_ms: float | None = Field(
        default=None, description="Tiempo de respuesta en ms"
    )
    error_code: str | None = Field(default=None, description="Código de error estable")
    message: str | None = Field(
        default=None,
        description="Mensaje técnico breve sin secretos",
    )


class RagGenerationReadiness(BaseModel):
    """Sanitized readiness for the two contractual RAG models."""

    status: str
    generation_model: str
    embedding_model: str
    dimensions: int
    eligible_reviewed_documents: int = 0
    error_code: str | None = None


class HealthReadyResponse(BaseModel):
    """Respuesta del endpoint /health/ready."""

    status: str = Field(description="Estado general: ready, degraded, not_ready")
    timestamp: str = Field(description="Fecha UTC en formato ISO 8601")
    request_id: str = Field(description="UUID v4 de correlación")
    rag_generation: RagGenerationReadiness | None = None


class HealthDependenciesResponse(BaseModel):
    """Respuesta del endpoint /health/dependencies."""

    status: str = Field(description="Estado agregado: ok, partial, error")
    timestamp: str = Field(description="Fecha UTC en formato ISO 8601")
    request_id: str = Field(description="UUID v4 de correlación")
    dependencies: dict[str, DependencyHealthSchema] = Field(
        description="Mapa de dependencias"
    )
