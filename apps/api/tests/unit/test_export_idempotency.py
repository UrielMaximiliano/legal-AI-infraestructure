"""Canonical request-hash and replay semantics for initial exports."""

from __future__ import annotations

from legal_ai.application.export_service import ExportService
from legal_ai.domain.enums import ExportFormat


def test_export_request_hash_is_canonical_and_format_sensitive() -> None:
    first = ExportService.request_hash(7, ExportFormat.PDF, "Editor")
    same = ExportService.request_hash(7, ExportFormat.PDF, "Editor")
    other_format = ExportService.request_hash(7, ExportFormat.DOCX, "Editor")
    other_actor = ExportService.request_hash(7, ExportFormat.PDF, "Other")

    assert first == same
    assert first != other_format
    assert first != other_actor
