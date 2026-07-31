"""Pruebas del middleware de request context."""

from __future__ import annotations

import pytest

from legal_ai.observability.request_context import RequestContextMiddleware


@pytest.mark.unit
class TestRequestContextMiddleware:
    """Pruebas para RequestContextMiddleware."""

    def test_sanitize_valid_id(self) -> None:
        """Verifica sanitización de ID válido."""
        result = RequestContextMiddleware._sanitize_request_id("test-123")
        assert result == "test-123"

    def test_sanitize_empty_id(self) -> None:
        """Verifica generación de UUID cuando el ID está vacío."""
        result = RequestContextMiddleware._sanitize_request_id("")
        assert len(result) == 36  # UUID format

    def test_sanitize_long_id(self) -> None:
        """Verifica generación de UUID cuando el ID es demasiado largo."""
        long_id = "a" * 200
        result = RequestContextMiddleware._sanitize_request_id(long_id)
        assert len(result) == 36

    def test_sanitize_special_chars(self) -> None:
        """Verifica limpieza de caracteres especiales."""
        result = RequestContextMiddleware._sanitize_request_id("test@#$%123")
        assert result == "test123"

    def test_sanitize_only_special_chars(self) -> None:
        """Verifica generación de UUID cuando solo hay caracteres especiales."""
        result = RequestContextMiddleware._sanitize_request_id("@#$%")
        assert len(result) == 36
