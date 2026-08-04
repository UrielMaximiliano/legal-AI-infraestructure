"""Artifact-integrity validation port."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ArtifactIntegrity(Protocol):
    def validate_docx(self, path: Path, expected_sha256: str | None = None) -> str: ...

    def validate_pdf(self, path: Path, expected_sha256: str | None = None) -> str: ...
