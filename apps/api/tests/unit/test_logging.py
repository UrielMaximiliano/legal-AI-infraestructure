"""Pruebas de configuración de logging."""

from __future__ import annotations

import logging

from legal_ai.observability.logging import setup_logging


class TestSetupLogging:
    """Pruebas para setup_logging."""

    def test_setup_default_level(self) -> None:
        """Verifica configuración con nivel por defecto."""
        setup_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_setup_debug_level(self) -> None:
        """Verifica configuración con nivel DEBUG."""
        setup_logging("DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_setup_warning_level(self) -> None:
        """Verifica configuración con nivel WARNING."""
        setup_logging("WARNING")
        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_handler_is_stream_handler(self) -> None:
        """Verifica que el handler es StreamHandler."""
        setup_logging()
        root = logging.getLogger()
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)

    def test_external_loggers_reduced_noise(self) -> None:
        """Verifica que librerías externas tienen nivel WARNING."""
        setup_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
        assert logging.getLogger("uvicorn.access").level == logging.WARNING
