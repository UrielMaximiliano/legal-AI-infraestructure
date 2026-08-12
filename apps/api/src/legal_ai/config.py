"""Configuración tipada de la aplicación mediante pydantic-settings."""

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


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
    endpoint: str = Field(
        default="/api/embed",
        validation_alias=AliasChoices("OLLAMA_EMBEDDING_ENDPOINT"),
        serialization_alias="OLLAMA_EMBEDDING_ENDPOINT",
    )
    embedding_context_length: int = Field(
        default=2048,
        validation_alias=AliasChoices("OLLAMA_EMBEDDING_CONTEXT_LENGTH"),
        serialization_alias="OLLAMA_EMBEDDING_CONTEXT_LENGTH",
        gt=0,
        le=32768,
    )

    def model_post_init(self, __context: object) -> None:
        """Valida que base_url y api_token estén configurados."""
        if not self.base_url:
            raise ValueError("OLLAMA_BASE_URL es obligatoria")
        if not self.api_token:
            raise ValueError("OLLAMA_EMBEDDING_TOKEN es obligatorio")
        if self.endpoint not in {"/api/embed", "/api/embeddings"}:
            raise ValueError("OLLAMA_EMBEDDING_ENDPOINT_INVALID")


class EmbeddingConfig(BaseSettings):
    """Contrato de embeddings de 005 (dimension nativa comprobada)."""

    model_config = {"extra": "ignore"}

    model: str = Field(default=EMBEDDING_MODEL, alias="OLLAMA_EMBEDDING_MODEL")
    dimensions: int = Field(
        default=EMBEDDING_DIMENSIONS, alias="EMBEDDING_DIMENSIONS", gt=0
    )

    @model_validator(mode="after")
    def validate_contract(self) -> "EmbeddingConfig":
        if self.model != EMBEDDING_MODEL:
            raise ValueError("OLLAMA_EMBEDDING_MODEL no coincide con el contrato 005")
        if self.dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(f"EMBEDDING_DIMENSIONS debe ser {EMBEDDING_DIMENSIONS}")
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


class RagConfig(BaseSettings):
    """Límites y contratos del pipeline RAG jurídico."""

    model_config = {"extra": "ignore"}

    generation_base_url: str = Field(
        default="http://host.docker.internal:11434",
        validation_alias=AliasChoices("OLLAMA_GENERATION_BASE_URL", "OLLAMA_BASE_URL"),
    )
    generation_endpoint: str = Field(
        default="/api/chat", alias="OLLAMA_GENERATION_ENDPOINT"
    )
    generation_model: str = Field(
        default="qwen3.6:35b", alias="OLLAMA_GENERATION_MODEL"
    )
    generation_token: str = Field(
        default="",
        validation_alias=AliasChoices("OLLAMA_GENERATION_TOKEN", "OLLAMA_API_TOKEN"),
    )
    generation_timeout_seconds: int = Field(
        default=300, alias="OLLAMA_GENERATION_TIMEOUT_SECONDS", gt=0, le=600
    )
    generation_max_retries: int = Field(
        default=1, alias="OLLAMA_GENERATION_MAX_RETRIES", ge=0, le=2
    )
    generation_context_window: int = Field(
        default=8_192, alias="OLLAMA_GENERATION_CONTEXT_LENGTH", ge=4_096, le=32_768
    )
    generation_max_output_tokens: int = Field(
        default=3_072, alias="OLLAMA_GENERATION_MAX_OUTPUT_TOKENS", ge=512, le=8_192
    )
    prompt_version: str = Field(default="rag-decree-v1", alias="RAG_PROMPT_VERSION")
    schema_version: int = Field(default=1, alias="RAG_SCHEMA_VERSION", gt=0)
    top_k: int = Field(default=8, alias="RAG_TOP_K", ge=3, le=20)
    candidate_pool_size: int = Field(
        default=24, alias="RAG_CANDIDATE_POOL_SIZE", ge=3, le=50
    )
    minimum_score: float = Field(default=0.0, alias="RAG_MINIMUM_SCORE", ge=0.0, le=1.0)
    max_context_bytes: int = Field(default=65_536, alias="RAG_MAX_CONTEXT_BYTES", gt=0)
    max_context_tokens_estimate: int = Field(
        default=2_048, alias="RAG_MAX_CONTEXT_TOKENS_ESTIMATE", gt=0
    )
    max_chunks_per_document: int = Field(
        default=2, alias="RAG_MAX_CHUNKS_PER_DOCUMENT", ge=1, le=10
    )
    max_chunks_per_section: int = Field(
        default=1, alias="RAG_MAX_CHUNKS_PER_SECTION", ge=1, le=5
    )
    schema_repair_attempts: int = Field(
        default=1, alias="RAG_SCHEMA_REPAIR_ATTEMPTS", ge=0, le=1
    )
    require_reviewed: bool = Field(default=True, alias="RAG_REQUIRE_REVIEWED")
    required_evaluation_split: str = Field(
        default="INDEX_90", alias="RAG_REQUIRED_EVALUATION_SPLIT"
    )
    required_document_subtype: str = Field(
        default="designacion_transitoria", alias="RAG_REQUIRED_DOCUMENT_SUBTYPE"
    )
    max_request_bytes: int = Field(
        default=256 * 1024, alias="RAG_MAX_REQUEST_BYTES", gt=0, le=2 * 1024 * 1024
    )

    @model_validator(mode="after")
    def validate_rag_contract(self) -> "RagConfig":
        if self.candidate_pool_size < self.top_k:
            raise ValueError("RAG_CANDIDATE_POOL_SIZE debe cubrir RAG_TOP_K")
        if self.generation_endpoint != "/api/chat":
            raise ValueError("OLLAMA_GENERATION_ENDPOINT_INVALID")
        if self.generation_model != "qwen3.6:35b":
            raise ValueError("OLLAMA_GENERATION_MODEL_INVALID")
        if self.generation_max_output_tokens >= self.generation_context_window:
            raise ValueError("OLLAMA_GENERATION_TOKEN_BUDGET_INVALID")
        if self.required_evaluation_split != "INDEX_90":
            raise ValueError("RAG_REQUIRED_EVALUATION_SPLIT_INVALID")
        if self.required_document_subtype not in {"designacion_transitoria", "decreto"}:
            raise ValueError("RAG_REQUIRED_DOCUMENT_SUBTYPE_INVALID")
        return self


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
        self.rag = RagConfig()
        self._ollama: OllamaConfig | None = None

    @property
    def ollama(self) -> OllamaConfig:
        """Configuración de Ollama (lazy-loaded)."""
        if self._ollama is None:
            self._ollama = OllamaConfig()
        return self._ollama


settings = Settings()
