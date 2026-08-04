"""Configuración tipada de la aplicación mediante pydantic-settings."""

from pathlib import Path

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


class ExportConfig(BaseSettings):
    """Límites y configuración operativa del incremento 004."""

    model_config = {"extra": "ignore"}

    storage_root: Path = Field(
        default=Path("/var/lib/legal-ai/exports"), alias="EXPORT_STORAGE_ROOT"
    )
    docx_generation_timeout_seconds: int = Field(
        default=30, alias="DOCX_GENERATION_TIMEOUT_SECONDS", gt=0
    )
    pdf_generation_timeout_seconds: int = Field(
        default=60, alias="PDF_GENERATION_TIMEOUT_SECONDS", gt=0
    )
    max_docx_size_bytes: int = Field(
        default=20 * 1024 * 1024, alias="MAX_DOCX_SIZE_BYTES", gt=0
    )
    max_pdf_size_bytes: int = Field(
        default=30 * 1024 * 1024, alias="MAX_PDF_SIZE_BYTES", gt=0
    )
    max_preview_size_bytes: int = Field(
        default=5 * 1024 * 1024, alias="MAX_PREVIEW_SIZE_BYTES", gt=0
    )
    max_final_snapshot_bytes: int = Field(
        default=2 * 1024 * 1024, alias="MAX_FINAL_SNAPSHOT_BYTES", gt=0
    )
    max_editable_content_bytes: int = Field(
        default=2 * 1024 * 1024, alias="MAX_EDITABLE_CONTENT_BYTES", gt=0
    )
    max_file_name_length: int = Field(default=120, alias="MAX_FILE_NAME_LENGTH", gt=0)
    max_relative_path_length: int = Field(
        default=500, alias="MAX_RELATIVE_PATH_LENGTH", gt=0
    )
    max_finalization_notes_length: int = Field(
        default=2000, alias="MAX_FINALIZATION_NOTES_LENGTH", gt=0
    )
    max_page_size: int = Field(default=100, alias="MAX_PAGE_SIZE", gt=0, le=100)
    export_idempotency_window_hours: int = Field(
        default=24, alias="EXPORT_IDEMPOTENCY_WINDOW_HOURS", gt=0
    )
    failed_attempt_retention_days: int = Field(
        default=180, alias="EXPORT_FAILED_ATTEMPT_RETENTION_DAYS", gt=0
    )
    temp_retention_hours: int = Field(
        default=24, alias="EXPORT_TEMP_RETENTION_HOURS", gt=0
    )
    orphan_retention_days: int = Field(
        default=7, alias="EXPORT_ORPHAN_RETENTION_DAYS", gt=0
    )
    pdf_eof_tail_bytes: int = Field(
        default=4096, alias="EXPORT_PDF_EOF_TAIL_BYTES", gt=0
    )

    def model_post_init(self, __context: object) -> None:
        """Validate relationships between configured limits."""
        if not self.storage_root.is_absolute() and not str(
            self.storage_root
        ).startswith(("/", "\\")):
            raise ValueError("EXPORT_STORAGE_ROOT debe ser una ruta absoluta")
        if self.max_file_name_length > self.max_relative_path_length:
            raise ValueError(
                "MAX_FILE_NAME_LENGTH no puede superar MAX_RELATIVE_PATH_LENGTH"
            )


class Settings:
    """Configuración agrupada de la aplicación."""

    def __init__(self) -> None:
        self.app = AppConfig()
        self.server = ServerConfig()
        self.logging = LoggingConfig()
        self.postgres = PostgreSQLConfig()
        self.export = ExportConfig()
        self._ollama: OllamaConfig | None = None

    @property
    def ollama(self) -> OllamaConfig:
        """Configuración de Ollama (lazy-loaded)."""
        if self._ollama is None:
            self._ollama = OllamaConfig()
        return self._ollama


settings = Settings()
