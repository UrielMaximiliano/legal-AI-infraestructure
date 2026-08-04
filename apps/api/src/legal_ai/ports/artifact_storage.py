"""Storage port declared before the local implementation phase."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol


class ArtifactStorage(Protocol):
    def resolve_relative(self, relative_path: str) -> Path: ...

    def create_temp(self, relative_path: str) -> Path: ...

    def atomic_replace(self, temporary: Path, relative_path: str) -> None: ...

    def stream(
        self, relative_path: str, chunk_size: int = 1024 * 1024
    ) -> Iterator[bytes]: ...

    def exists(self, relative_path: str) -> bool: ...

    def delete(self, relative_path: str) -> None: ...
