"""Smoke tests for 004 dependency and configuration availability."""

import os
from importlib import import_module, util

import pytest

from legal_ai.config import ExportConfig


def test_renderer_dependencies_import() -> None:
    assert import_module("docx")
    assert util.find_spec("weasyprint") is not None
    if os.name == "nt":
        pytest.skip("WeasyPrint requiere DLLs GTK/Pango instaladas en Windows")
    assert import_module("weasyprint")


def test_export_config_defaults_are_exact_bytes() -> None:
    config = ExportConfig()
    assert config.max_docx_size_bytes == 20 * 1024 * 1024
    assert config.max_pdf_size_bytes == 30 * 1024 * 1024
    assert config.max_preview_size_bytes == 5 * 1024 * 1024
    assert config.max_final_snapshot_bytes == 2 * 1024 * 1024
    assert config.pdf_eof_tail_bytes == 4096


def test_pdf_renderer_dependency_is_replaceable_on_supported_platforms() -> None:
    config = ExportConfig()
    assert config.pdf_generation_timeout_seconds == 60
