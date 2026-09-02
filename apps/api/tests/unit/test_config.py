"""Pruebas de validación de configuración."""

from __future__ import annotations

import os

import pytest


class TestAppConfig:
    """Pruebas para AppConfig."""

    def test_default_values(self) -> None:
        """Verifica valores por defecto de AppConfig."""
        os.environ.pop("APP_ENV", None)
        os.environ.pop("APP_NAME", None)
        os.environ.pop("APP_VERSION", None)

        from legal_ai.config import AppConfig

        config = AppConfig()
        assert config.env == "development"
        assert config.name == "legal-ai-api"
        assert config.version == "0.1.0"


class TestOllamaConfig:
    """Pruebas para OllamaConfig."""

    def test_required_fields(self) -> None:
        """Verifica que OLLAMA_BASE_URL y OLLAMA_API_TOKEN son obligatorios."""
        from pydantic import ValidationError

        from legal_ai.config import OllamaConfig

        os.environ.pop("OLLAMA_BASE_URL", None)
        os.environ.pop("OLLAMA_API_TOKEN", None)

        with pytest.raises(ValidationError):
            OllamaConfig()

    def test_timeout_validation(self) -> None:
        """Verifica restricciones de timeout."""
        from pydantic import ValidationError

        from legal_ai.config import OllamaConfig

        os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"
        os.environ["OLLAMA_API_TOKEN"] = "test-token"
        os.environ["OLLAMA_TIMEOUT_SECONDS"] = "0"

        with pytest.raises(ValidationError):
            OllamaConfig()

        os.environ["OLLAMA_TIMEOUT_SECONDS"] = "301"

        with pytest.raises(ValidationError):
            OllamaConfig()

        os.environ["OLLAMA_TIMEOUT_SECONDS"] = "5"

        config = OllamaConfig(
            OLLAMA_BASE_URL="http://localhost:11434",
            OLLAMA_API_TOKEN="test-token",
            OLLAMA_TIMEOUT_SECONDS=120,
        )
        assert config.timeout_seconds == 120

    def test_embedding_names_are_preferred_with_legacy_compatibility(self) -> None:
        from legal_ai.config import OllamaConfig

        config = OllamaConfig(
            OLLAMA_EMBEDDING_BASE_URL="https://ollama.example",
            OLLAMA_EMBEDDING_TOKEN="embedding-token",
            OLLAMA_EMBEDDING_TIMEOUT_SECONDS=7,
        )
        assert config.base_url == "https://ollama.example"
        assert config.api_token == "embedding-token"
        assert config.timeout_seconds == 7

    def test_embedding_endpoint_profile(self) -> None:
        from legal_ai.config import OllamaConfig

        config = OllamaConfig(
            OLLAMA_EMBEDDING_BASE_URL="https://ollama.example",
            OLLAMA_EMBEDDING_TOKEN="embedding-token",
            OLLAMA_EMBEDDING_ENDPOINT="/api/embeddings",
        )
        assert config.endpoint == "/api/embeddings"

        with pytest.raises(ValueError, match="ENDPOINT"):
            OllamaConfig(
                OLLAMA_EMBEDDING_BASE_URL="https://ollama.example",
                OLLAMA_EMBEDDING_TOKEN="embedding-token",
                OLLAMA_EMBEDDING_ENDPOINT="/api/unknown",
            )

    def test_embedding_context_length_profile(self) -> None:
        from pydantic import ValidationError

        from legal_ai.config import OllamaConfig

        config = OllamaConfig(
            OLLAMA_EMBEDDING_BASE_URL="https://ollama.example",
            OLLAMA_EMBEDDING_TOKEN="embedding-token",
            OLLAMA_EMBEDDING_CONTEXT_LENGTH=2048,
        )
        assert config.embedding_context_length == 2048

        for invalid in (0, 32769):
            with pytest.raises(ValidationError):
                OllamaConfig(
                    OLLAMA_EMBEDDING_BASE_URL="https://ollama.example",
                    OLLAMA_EMBEDDING_TOKEN="embedding-token",
                    OLLAMA_EMBEDDING_CONTEXT_LENGTH=invalid,
                )


class TestPostgreSQLConfig:
    """Pruebas para PostgreSQLConfig."""

    def test_database_url(self) -> None:
        """Verifica la construcción de la URL de conexión."""
        from legal_ai.config import PostgreSQLConfig

        config = PostgreSQLConfig()
        url = config.database_url
        assert "postgresql+asyncpg://" in url
        assert config.host in url
        assert str(config.port) in url

    def test_database_url_sync(self) -> None:
        """Verifica la URL síncrona para Alembic."""
        from legal_ai.config import PostgreSQLConfig

        config = PostgreSQLConfig()
        url = config.database_url_sync
        assert url.startswith("postgresql://")
        assert "asyncpg" not in url


class TestIMIDatabaseConfigs:
    """Pruebas para los límites de persistencia de IMI LEG."""

    def test_core_defaults_to_the_transactional_database(self) -> None:
        from legal_ai.config import CorePostgreSQLConfig

        config = CorePostgreSQLConfig()

        assert config.db == "imi_leg_core"
        assert config.host == "imi-core-postgres"
        assert config.database_url.startswith("postgresql+asyncpg://")

    def test_dispositions_rag_defaults_to_a_separate_vector_database(self) -> None:
        from legal_ai.config import DispositionsRagPostgreSQLConfig

        config = DispositionsRagPostgreSQLConfig()

        assert config.db == "imi_disposiciones_rag"
        assert config.host == "imi-disposiciones-rag-postgres"
        assert config.database_url_sync.startswith("postgresql://")
