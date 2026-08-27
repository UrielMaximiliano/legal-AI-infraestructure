"""PostgreSQL repository for corpus documents and human review CAS."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.domain.corpus import (
    CorpusDeduplicationRecord,
    CorpusDocument,
    CorpusDocumentNotFoundError,
    CorpusDocumentUpsertResult,
    CorpusIngestionStatus,
    InvalidReviewTransitionError,
    ReviewStatus,
    ReviewVersionMismatchError,
)

from .corpus_mappers import corpus_document_from_model, corpus_document_to_model
from .corpus_models import CorpusChunkModel, CorpusDocumentModel


class SQLAlchemyCorpusDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, document_id: uuid.UUID) -> CorpusDocument | None:
        model = await self._session.get(CorpusDocumentModel, document_id)
        return corpus_document_from_model(model) if model is not None else None

    async def create(self, document: CorpusDocument) -> CorpusDocument:
        model = corpus_document_to_model(document)
        self._session.add(model)
        await self._session.flush()
        return corpus_document_from_model(model)

    async def upsert(self, document: CorpusDocument) -> CorpusDocumentUpsertResult:
        """Insert or update a document and return the outcome directly.

        The result is deliberately value-like: callers never need to inspect
        mutable repository state to learn whether the write created, changed,
        or left the document unchanged.
        """

        return await _upsert(self, document)

    async def update(self, document: CorpusDocument) -> CorpusDocument:
        return (await self.upsert(document)).document

    async def update_processing_state(
        self,
        document_id: uuid.UUID,
        *,
        ingestion_status: str,
        embedding_status: str,
    ) -> CorpusDocument:
        try:
            ingestion_value = CorpusIngestionStatus(ingestion_status)
        except ValueError:
            raise ValueError("CORPUS_INGESTION_STATUS_INVALID") from None
        if embedding_status not in {"PENDING", "PROCESSING", "EMBEDDED", "FAILED"}:
            raise ValueError("CORPUS_EMBEDDING_STATUS_INVALID")
        result = await self._session.execute(
            update(CorpusDocumentModel)
            .where(CorpusDocumentModel.id == document_id)
            .values(
                ingestion_status=ingestion_value.value,
                embedding_status=embedding_status,
                updated_at=datetime.now(UTC),
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            raise CorpusDocumentNotFoundError("CORPUS_DOCUMENT_NOT_FOUND")
        await self._session.flush()
        document = await self.get(document_id)
        if document is None:  # pragma: no cover - guarded by rowcount
            raise CorpusDocumentNotFoundError("CORPUS_DOCUMENT_NOT_FOUND")
        return document

    async def list(
        self,
        *,
        document_type: str = "decreto",
        document_subtype: str = "designacion_transitoria",
        jurisdiction: str = "nacion",
        review_status: ReviewStatus | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[CorpusDocument]:
        if limit <= 0 or offset < 0:
            raise ValueError("CORPUS_PAGINATION_INVALID")
        statement = select(CorpusDocumentModel).where(
            CorpusDocumentModel.document_type == document_type,
            CorpusDocumentModel.document_subtype == document_subtype,
            CorpusDocumentModel.jurisdiction == jurisdiction,
        )
        if review_status is not None:
            statement = statement.where(
                CorpusDocumentModel.review_status == ReviewStatus(review_status).value
            )
        statement = (
            statement.order_by(CorpusDocumentModel.id).offset(offset).limit(limit)
        )
        result = await self._session.execute(statement)
        return tuple(corpus_document_from_model(model) for model in result.scalars())

    async def count_eligible_reviewed_documents(
        self,
        *,
        evaluation_split: str = "INDEX_90",
        document_type: str | None = None,
        document_subtype: str | None = None,
        jurisdiction: str | None = None,
    ) -> int:
        """Count active reviewed documents available in an evaluation split.

        Readiness is a corpus-capability check, so it must not assume one
        document taxonomy. Concrete retrieval requests still apply their
        validated document type, subtype, and jurisdiction filters.
        """

        predicates = [
            CorpusDocumentModel.review_status == ReviewStatus.REVIEWED.value,
            CorpusDocumentModel.active_generation.is_not(None),
            CorpusDocumentModel.metadata_json["evaluation_split"].as_string()
            == evaluation_split,
        ]
        for column, value in (
            (CorpusDocumentModel.document_type, document_type),
            (CorpusDocumentModel.document_subtype, document_subtype),
            (CorpusDocumentModel.jurisdiction, jurisdiction),
        ):
            if value is not None:
                predicates.append(column == value)

        result = await self._session.scalar(
            select(func.count())
            .select_from(CorpusDocumentModel)
            .where(*predicates)
        )
        return int(result or 0)

    async def count_holdout_matches(
        self, *, external_ids: Sequence[str], hashes: Sequence[str]
    ) -> int:
        """Count operational rows that would make a HOLDOUT manifest unsafe."""

        predicates = [
            CorpusDocumentModel.metadata_json["evaluation_split"].as_string()
            == "HOLDOUT_10",
        ]
        if external_ids:
            predicates.append(CorpusDocumentModel.external_id.in_(tuple(external_ids)))
        if hashes:
            predicates.extend(
                (
                    CorpusDocumentModel.raw_content_hash.in_(tuple(hashes)),
                    CorpusDocumentModel.normalized_content_hash.in_(tuple(hashes)),
                )
            )
        document_count = await self._session.scalar(
            select(func.count()).select_from(CorpusDocumentModel).where(or_(*predicates))
        )
        chunk_count = await self._session.scalar(
            select(func.count())
            .select_from(CorpusChunkModel)
            .where(
                CorpusChunkModel.metadata_json["evaluation_split"].as_string()
                == "HOLDOUT_10"
            )
        )
        return int(document_count or 0) + int(chunk_count or 0)

    async def compare_and_swap_review(
        self,
        document_id: uuid.UUID,
        *,
        expected_version: int,
        expected_status: ReviewStatus,
        new_status: ReviewStatus,
        reviewed_by: str,
        reason: str | None = None,
    ) -> CorpusDocument:
        current = await self.get(document_id)
        if current is None:
            raise CorpusDocumentNotFoundError("CORPUS_DOCUMENT_NOT_FOUND")
        if current.review_version != expected_version:
            raise ReviewVersionMismatchError("CORPUS_REVIEW_VERSION_MISMATCH")
        if current.review_status is not expected_status:
            raise InvalidReviewTransitionError("INVALID_CORPUS_REVIEW_TRANSITION")
        reviewed_at = datetime.now(UTC)
        current.transition_review(
            new_status,
            expected_version=expected_version,
            expected_status=expected_status,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            review_notes=reason,
        )
        result = await self._session.execute(
            update(CorpusDocumentModel)
            .where(
                CorpusDocumentModel.id == document_id,
                CorpusDocumentModel.review_version == expected_version,
                CorpusDocumentModel.review_status == expected_status.value,
            )
            .values(
                review_status=current.review_status.value,
                provenance_type=current.provenance_type.value,
                reviewed_by=current.reviewed_by,
                reviewed_at=current.reviewed_at,
                review_notes=current.review_notes,
                review_version=current.review_version,
                updated_at=reviewed_at,
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            raise ReviewVersionMismatchError("CORPUS_REVIEW_VERSION_MISMATCH")
        await self._session.flush()
        return current

    async def swap_generation(self, document_id: uuid.UUID, generation: int) -> None:
        """Publish a complete staged generation in one short transaction."""

        if generation <= 0:
            raise ValueError("CORPUS_GENERATION_INVALID")
        current = await self._session.get(CorpusDocumentModel, document_id)
        if current is None:
            raise CorpusDocumentNotFoundError("CORPUS_DOCUMENT_NOT_FOUND")
        await self._session.execute(
            update(CorpusDocumentModel)
            .where(CorpusDocumentModel.id == document_id)
            .values(active_generation=generation)
        )
        await self._session.flush()

    async def swap_generations(
        self, document_ids: Sequence[uuid.UUID], generation: int
    ) -> None:
        ids = tuple(document_ids)
        if generation <= 0:
            raise ValueError("CORPUS_GENERATION_INVALID")
        if not ids:
            return
        result = await self._session.execute(
            update(CorpusDocumentModel)
            .where(CorpusDocumentModel.id.in_(ids))
            .values(active_generation=generation)
        )
        if getattr(result, "rowcount", 0) != len(ids):
            raise CorpusDocumentNotFoundError("CORPUS_DOCUMENT_NOT_FOUND")
        await self._session.flush()

    async def update_processing_states(
        self,
        document_ids: Sequence[uuid.UUID],
        *,
        ingestion_status: str,
        embedding_status: str,
    ) -> None:
        ids = tuple(document_ids)
        try:
            ingestion_value = CorpusIngestionStatus(ingestion_status)
        except ValueError:
            raise ValueError("CORPUS_INGESTION_STATUS_INVALID") from None
        if embedding_status not in {"PENDING", "PROCESSING", "EMBEDDED", "FAILED"}:
            raise ValueError("CORPUS_EMBEDDING_STATUS_INVALID")
        if not ids:
            return
        result = await self._session.execute(
            update(CorpusDocumentModel)
            .where(CorpusDocumentModel.id.in_(ids))
            .values(
                ingestion_status=ingestion_value.value,
                embedding_status=embedding_status,
                updated_at=datetime.now(UTC),
            )
        )
        if getattr(result, "rowcount", 0) != len(ids):
            raise CorpusDocumentNotFoundError("CORPUS_DOCUMENT_NOT_FOUND")
        await self._session.flush()


CorpusDocumentRepository = SQLAlchemyCorpusDocumentRepository


class SQLAlchemyCorpusDeduplicationLookup:
    """Read-only, batched identity/hash lookup for dry-run estimation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lookup(
        self,
        *,
        identities: Sequence[tuple[str, str]],
        normalized_content_hashes: Sequence[str],
    ) -> tuple[CorpusDeduplicationRecord, ...]:
        predicates = [
            and_(
                CorpusDocumentModel.source_name == source_name,
                CorpusDocumentModel.external_id == external_id,
            )
            for source_name, external_id in identities
        ]
        filters = []
        if predicates:
            filters.append(or_(*predicates))
        if normalized_content_hashes:
            filters.append(
                CorpusDocumentModel.normalized_content_hash.in_(
                    tuple(normalized_content_hashes)
                )
            )
        if not filters:
            return ()
        result = await self._session.execute(
            select(
                CorpusDocumentModel.source_name,
                CorpusDocumentModel.external_id,
                CorpusDocumentModel.normalized_content_hash,
            ).where(
                CorpusDocumentModel.ingestion_status != CorpusIngestionStatus.FAILED,
                or_(*filters),
            )
        )
        return tuple(
            CorpusDeduplicationRecord(
                source_name=str(row.source_name),
                external_id=str(row.external_id),
                normalized_content_hash=str(row.normalized_content_hash),
            )
            for row in result
        )


async def _upsert(
    repository: SQLAlchemyCorpusDocumentRepository,
    document: CorpusDocument,
) -> CorpusDocumentUpsertResult:
    source_name = document.source_name.strip()
    if not source_name:
        raise ValueError("CORPUS_SOURCE_NAME_REQUIRED")
    if not isinstance(document.external_id, str) or not document.external_id.strip():
        raise ValueError("INVALID_CORPUS_EXTERNAL_ID")
    external_id = document.external_id.strip()
    result = await repository._session.execute(
        select(CorpusDocumentModel).where(
            CorpusDocumentModel.source_name == source_name,
            CorpusDocumentModel.external_id == external_id,
            CorpusDocumentModel.ingestion_status != "FAILED",
        )
    )
    model = result.scalars().first()
    if model is None:
        duplicate = await repository._session.execute(
            select(CorpusDocumentModel).where(
                CorpusDocumentModel.source_identifier == document.source_identifier,
                CorpusDocumentModel.raw_content_hash == document.raw_content_hash,
                CorpusDocumentModel.normalized_content_hash
                == document.normalized_content_hash,
                CorpusDocumentModel.ingestion_status != "FAILED",
                CorpusDocumentModel.active_generation.is_not(None),
            )
        )
        existing = duplicate.scalars().first()
        if existing is not None:
            return CorpusDocumentUpsertResult(
                "UNCHANGED", corpus_document_from_model(existing)
            )
        try:
            async with repository._session.begin_nested():
                model = corpus_document_to_model(document)
                repository._session.add(model)
                await repository._session.flush()
        except IntegrityError:
            result = await repository._session.execute(
                select(CorpusDocumentModel).where(
                    CorpusDocumentModel.source_name == source_name,
                    CorpusDocumentModel.external_id == external_id,
                    CorpusDocumentModel.ingestion_status != "FAILED",
                )
            )
            model = result.scalars().first()
            if model is None:
                raise ValueError("CORPUS_DOCUMENT_IDENTITY_CONFLICT") from None
            if (
                model.raw_content_hash != document.raw_content_hash
                or model.normalized_content_hash != document.normalized_content_hash
            ):
                raise ValueError("CORPUS_DOCUMENT_IDENTITY_CONFLICT") from None
            return CorpusDocumentUpsertResult(
                "UNCHANGED", corpus_document_from_model(model)
            )
        return CorpusDocumentUpsertResult("CREATED", corpus_document_from_model(model))

    pipeline_version = str(document.metadata.get("pipeline_version", "005"))
    content_unchanged = (
        model.raw_content_hash == document.raw_content_hash
        and model.normalized_content_hash == document.normalized_content_hash
        and model.normalization_version == document.normalization_version
        and model.chunking_version == document.chunking_version
        and model.created_by_pipeline_version == pipeline_version
    )
    if content_unchanged:
        return CorpusDocumentUpsertResult(
            "UNCHANGED", corpus_document_from_model(model)
        )

    # Content changes create a new staging candidate.  The currently active
    # generation remains searchable until the later atomic generation swap.
    model.title = document.title
    model.raw_content = document.raw_content
    model.raw_content_hash = document.raw_content_hash
    model.normalized_content = document.normalized_content
    model.normalized_content_hash = document.normalized_content_hash
    model.metadata_json = document.metadata
    model.ingestion_status = CorpusIngestionStatus.DISCOVERED
    model.embedding_status = "PENDING"
    model.review_status = ReviewStatus.PENDING_REVIEW.value
    model.provenance_type = "AUTOMATED"
    model.reviewed_by = None
    model.reviewed_at = None
    model.review_notes = None
    model.review_version += 1
    model.created_by_pipeline_version = pipeline_version
    model.normalization_version = document.normalization_version
    model.chunking_version = document.chunking_version
    model.updated_at = datetime.now(UTC)
    await repository._session.flush()
    return CorpusDocumentUpsertResult(
        "UPDATED",
        corpus_document_from_model(model),
        (
            "raw_content",
            "raw_content_hash",
            "normalized_content",
            "normalized_content_hash",
            "metadata",
            "ingestion_status",
            "embedding_status",
            "provenance_type",
            "review_status",
            "review_version",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "normalization_version",
            "chunking_version",
        ),
    )
