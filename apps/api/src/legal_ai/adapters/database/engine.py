"""SQLAlchemy async engine para PostgreSQL."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from legal_ai.config import settings


def create_engine() -> AsyncEngine:
    """Crea el engine async de SQLAlchemy con pool conservador."""
    return create_async_engine(
        settings.postgres.database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
