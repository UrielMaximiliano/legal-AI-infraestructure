"""Generic pagination schema."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse[T](BaseModel):
    """Paginated response schema."""

    page: int
    page_size: int
    total: int
    items: list[T]
