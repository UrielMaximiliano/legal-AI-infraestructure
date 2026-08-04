"""004 storage and renderer readiness tests without changing 003 health APIs."""

from __future__ import annotations

import sys
from pathlib import Path

from legal_ai.adapters.renderers.pdf_renderer import WeasyPrintPdfRenderer
from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage


def test_storage_health_is_sanitized_and_reports_unwritable_root(
    tmp_path: Path,
) -> None:
    healthy = LocalArtifactStorage(tmp_path / "exports")
    assert healthy.health() is True
    file_root = tmp_path / "not-a-directory"
    file_root.write_text("blocked", encoding="utf-8")
    assert LocalArtifactStorage(file_root).health() is False
    assert isinstance(healthy.health(), bool)


def test_pdf_renderer_health_is_sanitized(monkeypatch: object) -> None:
    # Importing a module as None makes Python report it as unavailable without
    # changing the renderer implementation or the health routes from 003.
    monkeypatch.setitem(sys.modules, "weasyprint", None)  # type: ignore[attr-defined]
    assert WeasyPrintPdfRenderer.health() is False
