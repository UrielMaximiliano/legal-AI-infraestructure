from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from legal_ai.cli.rag_benchmark import parse_prompt


def test_parse_prompt_reads_sanitized_benchmark_contract(tmp_path: Path) -> None:
    path = tmp_path / "prompt-0001-200924.md"
    path.write_text(
        """# Prompt 0001

- PDF de referencia: `200924.pdf`
- SHA-256: `e571a5144894ba01f211ed5a4bb2bbfbaed055d4a4e10b6c5aa3fb12a97f54d1`
- Nombre: `Decreto 1394/2012`

## Prompt para el modelo

> Prorrogar designaciones en un organismo nacional

Área temática: justicia.
Organismo competente: MINISTERIO DE JUSTICIA.
""",
        encoding="utf-8",
    )
    case = parse_prompt(path)
    assert case.number == 1
    assert case.external_id == "200924"
    assert case.reference_pdf == "200924.pdf"
    assert case.object_text == "Prorrogar designaciones en un organismo nacional"
    assert case.topic == "justicia"
    assert case.organization == "MINISTERIO DE JUSTICIA"


def test_parse_prompt_rejects_unexpected_filename(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_text("ignored", encoding="utf-8")
    with pytest.raises(ValueError, match="BENCHMARK_PROMPT_FILENAME_INVALID"):
        parse_prompt(path)


def test_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("legal_ai.cli.rag_benchmark")
    assert callable(module.main)
