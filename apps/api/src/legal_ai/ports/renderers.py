"""Replaceable renderer ports; implementations belong to later phases."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class CanonicalHtmlRenderer(Protocol):
    def render(self, snapshot: dict[str, Any]) -> str: ...


class DocxRenderer(Protocol):
    def render(self, snapshot: dict[str, Any], output_path: Path) -> None: ...


class PdfRenderer(Protocol):
    @staticmethod
    def health() -> bool: ...

    def render(self, html: str, output_path: Path) -> None: ...
