"""Configuración tipada de la aplicación mediante pydantic-settings."""

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
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

    base_url: str = Field(
        default="",
        validation_alias=AliasChoices("OLLAMA_EMBEDDING_BASE_URL", "OLLAMA_BASE_URL"),
        serialization_alias="OLLAMA_EMBEDDING_BASE_URL",
    )
    api_token: str = Field(
        default="",
        validation_alias=AliasChoices("OLLAMA_EMBEDDING_TOKEN", "OLLAMA_API_TOKEN"),
        serialization_alias="OLLAMA_EMBEDDING_TOKEN",
    )
    timeout_seconds: int = Field(
        default=5,
        validation_alias=AliasChoices(
            "OLLAMA_EMBEDDING_TIMEOUT_SECONDS", "OLLAMA_TIMEOUT_SECONDS"
        ),
        serialization_alias="OLLAMA_EMBEDDING_TIMEOUT_SECONDS",
        gt=0,
        le=30,
    )

    def model_post_init(self, __context: object) -> None:
        """Valida que base_url y api_token estén configurados."""
        if not self.base_url:
            raise ValueError("OLLAMA_BASE_URL es obligatoria")
        if not self.api_token:
            raise ValueError("OLLAMA_EMBEDDING_TOKEN es obligatorio")


class EmbeddingConfig(BaseSettings):
    """Contrato de embeddings de 005 (dimension nativa comprobada)."""

    model_config = {"extra": "ignore"}

    model: str = Field(default="qwen3-embedding:0.6b", alias="OLLAMA_EMBEDDING_MODEL")
    dimensions: int = Field(default=1024, alias="EMBEDDING_DIMENSIONS", gt=0)

    @model_validator(mode="after")
    def validate_contract(self) -> "EmbeddingConfig":
        if self.model != "qwen3-embedding:0.6b":
            raise ValueError("OLLAMA_EMBEDDING_MODEL no coincide con el contrato 005")
        if self.dimensions != 1024:
            raise ValueError("EMBEDDING_DIMENSIONS debe ser 1024")
        return self


class CorpusConfig(BaseSettings):
    """Límites de seguridad para descubrimiento e inferencia de corpus."""

    model_config = {"extra": "ignore"}

    embedding_batch_size: int = Field(
        default=16,
        validation_alias=AliasChoices(
            "OLLAMA_EMBEDDING_BATCH_SIZE", "CORPUS_EMBEDDING_BATCH_SIZE"
        ),
        serialization_alias="OLLAMA_EMBEDDING_BATCH_SIZE",
        gt=0,
        le=256,
    )
    embedding_timeout_seconds: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "OLLAMA_EMBEDDING_TIMEOUT_SECONDS", "CORPUS_EMBEDDING_TIMEOUT_SECONDS"
        ),
        serialization_alias="OLLAMA_EMBEDDING_TIMEOUT_SECONDS",
        gt=0,
        le=30,
    )
    max_input_bytes: int = Field(
        default=2 * 1024 * 1024,
        validation_alias=AliasChoices(
            "CORPUS_MAX_FILE_SIZE_BYTES", "CORPUS_MAX_INPUT_BYTES"
        ),
        serialization_alias="CORPUS_MAX_FILE_SIZE_BYTES",
        gt=0,
    )
    max_files: int = Field(
        default=10_000,
        validation_alias=AliasChoices("CORPUS_MAX_BATCH_FILES", "CORPUS_MAX_FILES"),
        serialization_alias="CORPUS_MAX_BATCH_FILES",
        gt=0,
    )
    max_chunks: int = Field(default=100_000, alias="CORPUS_MAX_CHUNKS", gt=0)
    max_queue_size: int = Field(
        default=32,
        validation_alias=AliasChoices(
            "EMBEDDING_QUEUE_MAX_SIZE", "CORPUS_MAX_QUEUE_SIZE"
        ),
        serialization_alias="EMBEDDING_QUEUE_MAX_SIZE",
        gt=0,
    )
    wait_timeout_seconds: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "EMBEDDING_WAIT_TIMEOUT_SECONDS", "CORPUS_WAIT_TIMEOUT_SECONDS"
        ),
        serialization_alias="EMBEDDING_WAIT_TIMEOUT_SECONDS",
        gt=0,
        le=300,
    )
    allowed_extensions: tuple[str, ...] = Field(
        default=(".txt", ".json", ".html"), alias="CORPUS_ALLOWED_EXTENSIONS"
    )

    @field_validator("allowed_extensions")
    @classmethod
    def normalize_extensions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in value
        )
        if not normalized:
            raise ValueError("CORPUS_ALLOWED_EXTENSIONS no puede estar vacía")
        return normalized


class SemanticSearchConfig(BaseSettings):
    """Límites y filtros contractuales de búsqueda semántica."""

    model_config = {"extra": "ignore"}

    reviewed_only: bool = Field(default=True, alias="SEMANTIC_SEARCH_REVIEWED_ONLY")
    max_top_k: int = Field(default=50, alias="SEMANTIC_SEARCH_MAX_TOP_K", gt=0, le=1000)
    timeout_seconds: int = Field(
        default=10, alias="SEMANTIC_SEARCH_TIMEOUT_SECONDS", gt=0, le=120
    )
    minimum_score: float = Field(
        default=0.0, alias="SEMANTIC_SEARCH_MINIMUM_SCORE", ge=0.0, le=1.0
    )


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
        self.embedding = EmbeddingConfig()
        self.corpus = CorpusConfig()
        self.semantic_search = SemanticSearchConfig()
        self._ollama: OllamaConfig | None = None

    @property
    def ollama(self) -> OllamaConfig:
        """Configuración de Ollama (lazy-loaded)."""
        if self._ollama is None:
            self._ollama = OllamaConfig()
        return self._ollama


settings = Settings()
