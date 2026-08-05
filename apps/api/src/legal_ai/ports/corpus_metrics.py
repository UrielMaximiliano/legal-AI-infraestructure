"""Small observability ports without payload or token leakage."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class MetricsPort(Protocol):
    def increment(
        self, name: str, *, value: int = 1, tags: dict[str, str] | None = None
    ) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
