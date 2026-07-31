"""Pruebas de validación de schemas Pydantic."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from legal_ai.schemas.errors import ErrorResponse
from legal_ai.schemas.health import (
    DependencyHealthSchema,
    HealthDependenciesResponse,
    HealthLiveResponse,
    HealthReadyResponse,
)


@pytest.mark.unit
class TestHealthLiveResponse:
    """Pruebas para HealthLiveResponse."""

    def test_valid_response(self) -> None:
        """Verifica respuesta válida."""
        response = HealthLiveResponse(
            status="ok",
            service="legal-ai-api",
            version="0.1.0",
            request_id="test-123",
        )
        assert response.status == "ok"
        assert response.service == "legal-ai-api"

    def test_missing_required_field(self) -> None:
        """Verifica error con campo requerido faltante."""
        with pytest.raises(ValidationError):
            HealthLiveResponse(status="ok")


@pytest.mark.unit
class TestHealthReadyResponse:
    """Pruebas para HealthReadyResponse."""

    def test_valid_ready(self) -> None:
        """Verifica respuesta ready."""
        response = HealthReadyResponse(
            status="ready",
            timestamp="2026-07-31T15:00:00+00:00",
            request_id="test-123",
        )
        assert response.status == "ready"

    def test_valid_not_ready(self) -> None:
        """Verifica respuesta not_ready."""
        response = HealthReadyResponse(
            status="not_ready",
            timestamp="2026-07-31T15:00:00+00:00",
            request_id="test-123",
        )
        assert response.status == "not_ready"


@pytest.mark.unit
class TestHealthDependenciesResponse:
    """Pruebas para HealthDependenciesResponse."""

    def test_valid_response_ok(self) -> None:
        """Verifica respuesta con todas las dependencias OK."""
        response = HealthDependenciesResponse(
            status="ok",
            timestamp="2026-07-31T15:00:00+00:00",
            request_id="test-123",
            dependencies={
                "postgres": DependencyHealthSchema(status="ok", latency_ms=10.0),
                "pgvector": DependencyHealthSchema(status="ok"),
                "ollama": DependencyHealthSchema(status="ok", latency_ms=30.0),
            },
        )
        assert response.status == "ok"
        assert len(response.dependencies) == 3

    def test_valid_response_partial(self) -> None:
        """Verifica respuesta con dependencias parciales."""
        response = HealthDependenciesResponse(
            status="partial",
            timestamp="2026-07-31T15:00:00+00:00",
            request_id="test-123",
            dependencies={
                "postgres": DependencyHealthSchema(status="ok"),
                "pgvector": DependencyHealthSchema(status="ok"),
                "ollama": DependencyHealthSchema(
                    status="timeout",
                    latency_ms=5000.0,
                    error_code="OLLAMA_TIMEOUT",
                    message="Timeout",
                ),
            },
        )
        assert response.status == "partial"
        assert response.dependencies["ollama"].error_code == "OLLAMA_TIMEOUT"


@pytest.mark.unit
class TestDependencyHealthSchema:
    """Pruebas para DependencyHealthSchema."""

    def test_with_auth_errors(self) -> None:
        """Verifica estados de autenticación."""
        unauthorized = DependencyHealthSchema(
            status="unauthorized",
            error_code="OLLAMA_UNAUTHORIZED",
        )
        assert unauthorized.status == "unauthorized"

        forbidden = DependencyHealthSchema(
            status="forbidden",
            error_code="OLLAMA_FORBIDDEN",
        )
        assert forbidden.status == "forbidden"

        rate_limited = DependencyHealthSchema(
            status="rate_limited",
            error_code="OLLAMA_RATE_LIMITED",
        )
        assert rate_limited.status == "rate_limited"


@pytest.mark.unit
class TestErrorResponse:
    """Pruebas para ErrorResponse."""

    def test_valid_error_response(self) -> None:
        """Verifica respuesta de error válida."""
        response = ErrorResponse(
            error_code="POSTGRES_UNAVAILABLE",
            message="PostgreSQL no accesible",
            request_id="test-123",
        )
        assert response.error_code == "POSTGRES_UNAVAILABLE"
        assert response.request_id == "test-123"

    def test_error_response_without_request_id(self) -> None:
        """Verifica respuesta de error sin request_id."""
        response = ErrorResponse(
            error_code="OLLAMA_TIMEOUT",
            message="Timeout",
        )
        assert response.error_code == "OLLAMA_TIMEOUT"
        assert response.request_id is None

    def test_missing_required_field(self) -> None:
        """Verifica error con campo requerido faltante."""
        with pytest.raises(ValidationError):
            ErrorResponse(error_code="TEST")
