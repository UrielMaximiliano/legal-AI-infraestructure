"""Preparación de documentos: normalización, metadatos y chunking sin DB."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from legal_ai.adapters.filesystem_corpus import CorpusSourceFile
from legal_ai.application.corpus_ingestion.configuration import (
    CorpusIngestionConfiguration,
)
from legal_ai.application.corpus_metadata import CorpusMetadataService
from legal_ai.application.corpus_normalization import (
    CorpusNormalizationService,
    NormalizationConfig,
)
from legal_ai.application.legal_chunking import LegalChunk, LegalChunkingService
from legal_ai.domain.corpus import CorpusDocument


@dataclass(frozen=True, slots=True)
class PreparedDocument:
    source: CorpusSourceFile
    document: CorpusDocument
    chunks: tuple[LegalChunk, ...]


def error_code(exc: BaseException, default: str) -> str:
    """Código estable y sanitizado para reportes; nunca incluye contenido."""

    value = getattr(exc, "code", None)
    if isinstance(value, str) and value and value.replace("_", "").isalnum():
        return value[:80]
    return default


class DocumentPreparer:
    """Construye el agregado de dominio completo antes de abrir transacciones."""

    def __init__(
        self,
        *,
        normalizer: CorpusNormalizationService | None = None,
        metadata_service: CorpusMetadataService | None = None,
        chunker: LegalChunkingService | None = None,
    ) -> None:
        self.normalizer = normalizer or CorpusNormalizationService()
        self.metadata_service = metadata_service or CorpusMetadataService()
        self.chunker = chunker or LegalChunkingService()

    def prepare(
        self, source: CorpusSourceFile, config: CorpusIngestionConfiguration
    ) -> PreparedDocument:
        normalized = self.normalizer.normalize(
            source.text,
            config=self._normalizer_config(config),
        )
        values: dict[str, object] = dict(source.metadata or {})
        values.update(
            {
                "external_id": values.get(
                    "external_id", PurePosixPath(source.source_identifier).stem
                ),
                "source_name": values.get("source_name", config.source_name),
                "source_identifier": values.get(
                    "source_identifier", source.source_identifier
                ),
                "document_type": values.get("document_type", config.document_type),
                "document_subtype": values.get(
                    "document_subtype", config.document_subtype
                ),
                "jurisdiction": values.get("jurisdiction", config.jurisdiction),
                "language": values.get("language", config.language),
                "normalization_version": config.normalization_version,
                "chunking_version": config.chunking_version,
                "pipeline_version": "005",
            }
        )
        metadata = self.metadata_service.validate(values)
        document_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"005:{metadata.source_name}:{metadata.external_id}",
        )
        chunks = self.chunker.chunk(
            normalized.normalized_content,
            document_id=document_id,
            chunking_version=config.chunking_version,
            normalization_version=config.normalization_version,
        )
        title_value = values.get("title")
        document = CorpusDocument(
            id=document_id,
            source_identifier=metadata.source_identifier,
            raw_content=normalized.raw_content,
            normalized_content=normalized.normalized_content,
            raw_content_hash=normalized.raw_content_hash,
            normalized_content_hash=normalized.normalized_content_hash,
            external_id=metadata.external_id,
            source_name=metadata.source_name,
            title=title_value if isinstance(title_value, str) else None,
            document_type=metadata.document_type,
            document_subtype=metadata.document_subtype,
            jurisdiction=metadata.jurisdiction,
            language=metadata.language,
            organization=metadata.organization,
            source_url=metadata.source_url,
            publication_date=metadata.publication_date,
            metadata=metadata.sanitized_dict(),
            normalization_version=config.normalization_version,
            chunking_version=config.chunking_version,
        )
        return PreparedDocument(source=source, document=document, chunks=chunks)

    def validate_source(
        self, source: CorpusSourceFile, config: CorpusIngestionConfiguration
    ) -> tuple[int, str, str]:
        """Validación ligera del dry-run: (chunks, hash normalizado, external_id)."""

        normalized = self.normalizer.normalize(
            source.text,
            config=self._normalizer_config(config),
        )
        payload: Mapping[str, object] = dict(source.metadata or {})
        values = dict(payload)
        values.update(
            {
                "external_id": values.get(
                    "external_id", PurePosixPath(source.source_identifier).stem
                ),
                "source_name": values.get("source_name", config.source_name),
                "source_identifier": source.source_identifier,
                "document_type": values.get("document_type", config.document_type),
                "document_subtype": values.get(
                    "document_subtype", config.document_subtype
                ),
                "jurisdiction": values.get("jurisdiction", config.jurisdiction),
                "language": values.get("language", config.language),
                "normalization_version": config.normalization_version,
                "chunking_version": config.chunking_version,
            }
        )
        metadata = self.metadata_service.validate(values)
        chunks = self.chunker.chunk(
            normalized.normalized_content,
            chunking_version=config.chunking_version,
            normalization_version=config.normalization_version,
        )
        external_id = str(metadata.external_id)
        return len(chunks), normalized.normalized_content_hash, external_id

    def _normalizer_config(
        self, config: CorpusIngestionConfiguration
    ) -> NormalizationConfig:
        return replace(self.normalizer.config, version=config.normalization_version)
