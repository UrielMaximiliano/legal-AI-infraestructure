"""Configuración tipada de la aplicación mediante pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    """Configuración principal de la aplicación."""

    model_config = {"env_prefix": "APP_"}

    env: str = Field(default="development", alias="APP_ENV")
    name: str = Field(default="legal-ai-api", alias="APP_NAME")
    version: str = Field(default="0.1.0", alias="APP_VERSION")


class ServerConfig(BaseSettings):
    """Configuración del servidor HTTP."""

    model_config = {"env_prefix": "API_"}

    host: str = Field(default="0.0.0.0", alias="API_HOST")
    port: int = Field(default=8000, alias="API_PORT")


class LoggingConfig(BaseSettings):
    """Configuración de logging."""

    level: str = Field(default="INFO", alias="LOG_LEVEL")


class PostgreSQLConfig(BaseSettings):
    """Configuración de conexión a PostgreSQL."""

    model_config = {"env_prefix": "POSTGRES_"}

    host: str = Field(default="postgres", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    db: str = Field(default="legal_ai", alias="POSTGRES_DB")
    user: str = Field(default="legal_ai", alias="POSTGRES_USER")
    password: str = Field(default="change-me", alias="POSTGRES_PASSWORD")

    @property
    def database_url(self) -> str:
        """Construye la URL de conexión asyncpg."""
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Construye la URL de conexión síncrona para Alembic."""
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class OllamaConfig(BaseSettings):
    """Configuración de conexión a Ollama."""

    model_config = {"env_prefix": "OLLAMA_"}

    base_url: str = Field(default="", alias="OLLAMA_BASE_URL")
    api_token: str = Field(default="", alias="OLLAMA_API_TOKEN")
    timeout_seconds: int = Field(default=5, alias="OLLAMA_TIMEOUT_SECONDS", gt=0, le=30)

    def model_post_init(self, __context: object) -> None:
        """Valida que base_url y api_token estén configurados."""
        if not self.base_url:
            raise ValueError("OLLAMA_BASE_URL es obligatoria")
        if not self.api_token:
            raise ValueError("OLLAMA_API_TOKEN es obligatorio")


class Settings:
    """Configuración agrupada de la aplicación."""

    def __init__(self) -> None:
        self.app = AppConfig()
        self.server = ServerConfig()
        self.logging = LoggingConfig()
        self.postgres = PostgreSQLConfig()
        self._ollama: OllamaConfig | None = None

    @property
    def ollama(self) -> OllamaConfig:
        """Configuración de Ollama (lazy-loaded)."""
        if self._ollama is None:
            self._ollama = OllamaConfig()
        return self._ollama


settings = Settings()
