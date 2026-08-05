"""Explicit ORM/domain mappers for corpus persistence.

The functions use an allowlist and never expose raw or normalized content in
safe representations.  Loading a document is an internal repository action;
routes and reports must use a separate DTO.
"""

from __future__ import annotations

from legal_ai.domain.corpus import (
    CorpusChunk,
    CorpusDocument,
    CorpusIngestionStatus,
    ProvenanceType,
    ReviewStatus,
)

from .corpus_models import CorpusChunkModel, CorpusDocumentModel


def corpus_document_to_model(document: CorpusDocument) -> CorpusDocumentModel:
    source_name = document.source_name.strip()
    if not source_name:
        raise ValueError("CORPUS_SOURCE_NAME_REQUIRED")
    if not isinstance(document.external_id, str) or not document.external_id.strip():
        raise ValueError("INVALID_CORPUS_EXTERNAL_ID")
    return CorpusDocumentModel(
        id=document.id,
        external_id=document.external_id.strip(),
        title=document.title,
        document_type=document.document_type,
        document_subtype=document.document_subtype,
        jurisdiction=document.jurisdiction,
        language=document.language,
        organization=document.organization,
        source_name=source_name,
        source_identifier=document.source_identifier,
        source_url=document.source_url,
        publication_date=document.publication_date,
        raw_content=document.raw_content,
        raw_content_hash=document.raw_content_hash,
        normalized_content=document.normalized_content,
        normalized_content_hash=document.normalized_content_hash,
        metadata_json=document.metadata,
        provenance_type=document.provenance_type.value,
        review_status=document.review_status.value,
        review_version=document.review_version,
        reviewed_by=document.reviewed_by,
        reviewed_at=document.reviewed_at,
        review_notes=document.review_notes,
        ingestion_status=document.ingestion_status,
        created_by_pipeline_version=str(
            document.metadata.get("pipeline_version", "005")
        ),
        normalization_version=document.normalization_version,
        chunking_version=document.chunking_version,
        active_generation=document.active_generation,
    )


def corpus_document_from_model(model: CorpusDocumentModel) -> CorpusDocument:
    return CorpusDocument(
        id=model.id,
        source_identifier=model.source_identifier,
        raw_content=model.raw_content,
        normalized_content=model.normalized_content,
        raw_content_hash=model.raw_content_hash,
        normalized_content_hash=model.normalized_content_hash,
        review_status=ReviewStatus(model.review_status),
        provenance_type=ProvenanceType(model.provenance_type),
        review_version=model.review_version,
        reviewed_by=model.reviewed_by,
        reviewed_at=model.reviewed_at,
        review_notes=model.review_notes,
        ingestion_status=CorpusIngestionStatus(model.ingestion_status),
        external_id=model.external_id,
        source_name=model.source_name,
        title=model.title,
        document_type=model.document_type,
        document_subtype=model.document_subtype,
        jurisdiction=model.jurisdiction,
        language=model.language,
        organization=model.organization,
        source_url=model.source_url,
        publication_date=model.publication_date,
        metadata=model.metadata_json,
        normalization_version=model.normalization_version,
        chunking_version=model.chunking_version,
        active_generation=model.active_generation,
    )


def corpus_chunk_to_model(chunk: CorpusChunk) -> CorpusChunkModel:
    return CorpusChunkModel(
        id=chunk.id,
        document_id=chunk.document_id,
        generation=chunk.generation,
        state=chunk.state,
        section_type=chunk.section_type,
        section_index=chunk.section_index,
        paragraph_index=chunk.paragraph_index,
        article_number=chunk.article_number,
        content=chunk.content,
        content_hash=chunk.content_hash,
        token_count=chunk.token_count,
        embedding=list(chunk.embedding) if chunk.embedding is not None else None,
        embedding_model=(
            chunk.embedding_model
            if chunk.embedding is None or chunk.embedding_model
            else "qwen3-embedding:0.6b"
        ),
        embedding_dimensions=(
            chunk.embedding_dimensions
            if chunk.embedding is None or chunk.embedding_dimensions is not None
            else 1024
        ),
        normalization_version=chunk.normalization_version,
        chunking_version=chunk.chunking_version,
        metadata_json=chunk.metadata,
    )


def corpus_chunk_from_model(model: CorpusChunkModel) -> CorpusChunk:
    embedding = (
        tuple(float(value) for value in model.embedding)
        if model.embedding is not None
        else None
    )
    return CorpusChunk(
        id=model.id,
        document_id=model.document_id,
        content=model.content,
        content_hash=model.content_hash,
        generation=model.generation,
        section_index=model.section_index,
        paragraph_index=model.paragraph_index,
        embedding=embedding,
        section_type=model.section_type,
        article_number=model.article_number,
        token_count=model.token_count,
        chunking_version=model.chunking_version,
        normalization_version=model.normalization_version,
        state=model.state,
        embedding_model=model.embedding_model,
        embedding_dimensions=model.embedding_dimensions,
        metadata=model.metadata_json,
    )
