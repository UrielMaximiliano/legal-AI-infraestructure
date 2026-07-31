"""Modelos de dominio para health checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HealthStatus(StrEnum):
    """Estados individuales posibles para una dependencia."""

    OK = "ok"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    MISCONFIGURED = "misconfigured"
    INVALID_RESPONSE = "invalid_response"
    MISSING = "missing"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    RATE_LIMITED = "rate_limited"


class ReadinessStatus(StrEnum):
    """Estados generales de readiness para /health/ready."""

    READY = "ready"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


class AggregateStatus(StrEnum):
    """Estados agregados de diagnóstico para /health/dependencies."""

    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"


@dataclass(frozen=True)
class DependencyHealth:
    """Resultado de la verificación de una dependencia individual."""

    status: HealthStatus
    latency_ms: float | None = None
    error_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class HealthCheckResult:
    """Resultado del health check de una dependencia."""

    postgres: DependencyHealth
    pgvector: DependencyHealth
    ollama: DependencyHealth
