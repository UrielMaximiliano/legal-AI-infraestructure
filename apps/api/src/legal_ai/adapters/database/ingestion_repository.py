"""Compatibility import surface for the phase-9 ingestion repositories."""

from .ingestion_repositories import (
    EmbeddingBatchRepository,
    IngestionFailureRepository,
    IngestionRunRepository,
    SQLAlchemyEmbeddingBatchRepository,
    SQLAlchemyIngestionFailureRepository,
    SQLAlchemyIngestionRunRepository,
)

__all__ = [
    "EmbeddingBatchRepository",
    "IngestionFailureRepository",
    "IngestionRunRepository",
    "SQLAlchemyEmbeddingBatchRepository",
    "SQLAlchemyIngestionFailureRepository",
    "SQLAlchemyIngestionRunRepository",
]
