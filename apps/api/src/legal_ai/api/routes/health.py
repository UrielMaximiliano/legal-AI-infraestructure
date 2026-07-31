"""Controladores de los endpoints de health check."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.health import PostgreSQLHealthAdapter
from legal_ai.adapters.ollama.client import create_ollama_client
from legal_ai.adapters.ollama.health import OllamaHealthAdapter
from legal_ai.application.health_service import HealthService
from legal_ai.config import settings
from legal_ai.schemas.health import (
    DependencyHealthSchema,
    HealthDependenciesResponse,
    HealthLiveResponse,
    HealthReadyResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _get_health_service() -> HealthService:
    """Crea una instancia del servicio de health checks."""
    engine = create_engine()
    db_adapter = PostgreSQLHealthAdapter(engine)
    client = create_ollama_client()
    ollama_adapter = OllamaHealthAdapter(client)
    return HealthService(db_adapter, ollama_adapter)


@router.get("/health/live", response_model=HealthLiveResponse)
async def health_live(request: Request) -> HealthLiveResponse:
    """Liveness: indica que el proceso HTTP está activo."""
    return HealthLiveResponse(
        status="ok",
        service=settings.app.name,
        version=settings.app.version,
        request_id=request.state.request_id,
    )


@router.get("/health/ready", response_model=HealthReadyResponse)
async def health_ready(request: Request, response: Response) -> HealthReadyResponse:
    """Readiness: indica si la aplicación está preparada."""
    service = _get_health_service()
    try:
        result = await service.check_all()
        readiness = service.compute_readiness(result)
        if readiness != "ready":
            response.status_code = 503
        return HealthReadyResponse(
            status=readiness,
            timestamp=service.now_utc(),
            request_id=request.state.request_id,
        )
    except Exception:
        logger.exception("Error interno en health ready")
        response.status_code = 500
        return HealthReadyResponse(
            status="not_ready",
            timestamp=service.now_utc(),
            request_id=request.state.request_id,
        )
    finally:
        pass

        # El engine se cierra en el lifespan, no aquí


@router.get("/health/dependencies", response_model=HealthDependenciesResponse)
async def health_dependencies(
    request: Request, response: Response
) -> HealthDependenciesResponse:
    """Diagnóstico: expone estado individual de cada dependencia."""
    service = _get_health_service()
    try:
        result = await service.check_all()
        aggregate = service.compute_aggregate_status(result)
        return HealthDependenciesResponse(
            status=aggregate.value,
            timestamp=service.now_utc(),
            request_id=request.state.request_id,
            dependencies={
                "postgres": DependencyHealthSchema(
                    status=result.postgres.status.value,
                    latency_ms=result.postgres.latency_ms,
                    error_code=result.postgres.error_code,
                    message=result.postgres.message,
                ),
                "pgvector": DependencyHealthSchema(
                    status=result.pgvector.status.value,
                    latency_ms=result.pgvector.latency_ms,
                    error_code=result.pgvector.error_code,
                    message=result.pgvector.message,
                ),
                "ollama": DependencyHealthSchema(
                    status=result.ollama.status.value,
                    latency_ms=result.ollama.latency_ms,
                    error_code=result.ollama.error_code,
                    message=result.ollama.message,
                ),
            },
        )
    except Exception:
        logger.exception("Error interno en health dependencies")
        response.status_code = 500
        return HealthDependenciesResponse(
            status="error",
            timestamp=service.now_utc(),
            request_id=request.state.request_id,
            dependencies={
                "postgres": DependencyHealthSchema(
                    status="unavailable",
                    error_code="INTERNAL_DIAGNOSTIC_ERROR",
                    message="Error interno del diagnóstico",
                ),
                "pgvector": DependencyHealthSchema(
                    status="unavailable",
                    error_code="INTERNAL_DIAGNOSTIC_ERROR",
                    message="Error interno del diagnóstico",
                ),
                "ollama": DependencyHealthSchema(
                    status="unavailable",
                    error_code="INTERNAL_DIAGNOSTIC_ERROR",
                    message="Error interno del diagnóstico",
                ),
            },
        )
