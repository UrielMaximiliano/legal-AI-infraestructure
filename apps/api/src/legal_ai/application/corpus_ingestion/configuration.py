"""Configuración declarativa del pipeline de ingesta 005."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


@dataclass(frozen=True, slots=True)
class CorpusIngestionConfiguration:
    model: str = EMBEDDING_MODEL
    dimensions: int = EMBEDDING_DIMENSIONS
    source_name: str = "filesystem"
    document_type: str = "decreto"
    document_subtype: str = "designacion_transitoria"
    jurisdiction: str = "nacion"
    language: str = "es"
    normalization_version: str = "005-nfc-v1"
    chunking_version: str = "005-legal-v1"
    batch_size: int = 16
    max_chunks: int = 100_000

    def validate(self) -> None:
        if self.model != EMBEDDING_MODEL or self.dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError("EMBEDDING_CONTRACT_INVALID")
        if not self.source_name.strip():
            raise ValueError("CORPUS_SOURCE_NAME_INVALID")
        if (
            not self.document_type.strip()
            or not self.document_subtype.strip()
            or not self.jurisdiction.strip()
            or not self.language.strip()
            or not self.normalization_version.strip()
            or not self.chunking_version.strip()
            or self.batch_size <= 0
            or self.batch_size > 256
            or self.max_chunks <= 0
        ):
            raise ValueError("CORPUS_CONFIGURATION_INVALID")


def limit_identifiers(
    identifiers: tuple[str, ...], limit: int | None
) -> tuple[str, ...]:
    """Aplica el límite opcional de archivos descubiertos."""

    if limit is None:
        return identifiers
    if limit <= 0:
        raise ValueError("CORPUS_LIMIT_INVALID")
    return identifiers[:limit]


def configuration_snapshot(config: CorpusIngestionConfiguration) -> dict[str, Any]:
    """Snapshot canónico usado para el hash de configuración del run."""

    return asdict(config)
