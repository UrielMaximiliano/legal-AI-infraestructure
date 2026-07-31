"""Interfaz abstracta para verificación de salud de PostgreSQL."""

from __future__ import annotations

from abc import ABC, abstractmethod

from legal_ai.domain.health import DependencyHealth


class DatabaseHealthPort(ABC):
    """Puerto abstracto para verificación de salud de PostgreSQL."""

    @abstractmethod
    async def check(self) -> DependencyHealth:
        """Verifica la conectividad con PostgreSQL y pgvector."""
        ...
