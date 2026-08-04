"""Optional real renderer checks; PDF is skipped when native libs are absent."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Cm

from legal_ai.adapters.renderers.pdf_renderer import WeasyPrintPdfRenderer

FIXTURE_DOCX = Path(__file__).parents[1] / "fixtures" / "valid_document.docx"


@pytest.mark.integration
def test_real_docx_is_a_zip_with_required_xml(tmp_path: Path) -> None:
    with zipfile.ZipFile(FIXTURE_DOCX) as archive:
        names = set(archive.namelist())
    assert "[Content_Types].xml" in names
    assert "word/document.xml" in names
    document = Document(FIXTURE_DOCX)
    section = document.sections[0]
    assert abs(section.page_width - Cm(21)) < 1000
    assert abs(section.page_height - Cm(29.7)) < 1000
    assert abs(section.top_margin - Cm(2.5)) < 1000
    assert abs(section.bottom_margin - Cm(2.5)) < 1000
    assert abs(section.left_margin - Cm(3)) < 1000
    assert abs(section.right_margin - Cm(2)) < 1000


@pytest.mark.integration
def test_real_pdf_when_native_runtime_is_available(tmp_path: Path) -> None:
    if not WeasyPrintPdfRenderer.health():
        pytest.skip("WeasyPrint native runtime unavailable")
    output = tmp_path / "11111111-1111-4111-8111-111111111111_v1.pdf"
    WeasyPrintPdfRenderer().render(
        "<!doctype html><html><body>Prueba</body></html>", output
    )
    assert output.read_bytes().startswith(b"%PDF-")
    assert b"%%EOF" in output.read_bytes()[-4096:]
