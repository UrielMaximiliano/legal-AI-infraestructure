"""Interfaz abstracta para verificación de salud de Ollama."""

from __future__ import annotations

from abc import ABC, abstractmethod

from legal_ai.domain.health import DependencyHealth


class OllamaHealthPort(ABC):
    """Puerto abstracto para verificación de salud de Ollama."""

    @abstractmethod
    async def check(self) -> DependencyHealth:
        """Verifica la conectividad con Ollama."""
        ...
