"""Read-only preflight and row locking for safe staged-index activation."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal
from typing import cast as type_cast

from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from legal_ai.domain.corpus import CorpusActivationDocument, CorpusActivationSnapshot
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

from .corpus_models import CorpusChunkModel, CorpusDocumentModel


class SQLAlchemyCorpusActivationRepository:
    """Inspect activation invariants without exposing document text or vectors."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _is_index_document() -> ColumnElement[bool]:
        return type_cast(
            "ColumnElement[bool]",
            CorpusDocumentModel.metadata_json["evaluation_split"].as_string()
            == "INDEX_90",
        )

    @staticmethod
    def _embedding_is_valid() -> ColumnElement[bool]:
        vector_text = cast(CorpusChunkModel.embedding, Text)
        return and_(
            CorpusChunkModel.embedding.is_not(None),
            CorpusChunkModel.embedding_dimensions == EMBEDDING_DIMENSIONS,
            func.vector_dims(CorpusChunkModel.embedding) == EMBEDDING_DIMENSIONS,
            CorpusChunkModel.embedding_model == EMBEDDING_MODEL,
            ~vector_text.op("~*")("nan|infinity"),
        )

    async def inspect(self, *, generation: int) -> CorpusActivationSnapshot:
        if generation <= 0:
            raise ValueError("CORPUS_GENERATION_INVALID")
        database_name = str(await self._session.scalar(select(func.current_database())))
        index_filter = self._is_index_document()
        target_filter = CorpusChunkModel.generation == generation
        valid_embedding = self._embedding_is_valid()

        document_rows = (
            await self._session.execute(
                select(
                    CorpusDocumentModel.id,
                    CorpusDocumentModel.active_generation,
                    CorpusDocumentModel.review_version,
                    func.count(CorpusChunkModel.id).filter(target_filter).label("total"),
                    func.count(CorpusChunkModel.id)
                    .filter(and_(target_filter, CorpusChunkModel.state == "STAGED"))
                    .label("staged"),
                    func.count(CorpusChunkModel.id)
                    .filter(and_(target_filter, CorpusChunkModel.state == "ACTIVE"))
                    .label("active"),
                    func.count(CorpusChunkModel.id)
                    .filter(and_(target_filter, valid_embedding))
                    .label("valid"),
                    func.count(CorpusChunkModel.id)
                    .filter(
                        and_(
                            CorpusChunkModel.state == "ACTIVE",
                            CorpusChunkModel.generation != generation,
                        )
                    )
                    .label("incompatible_active"),
                    func.count(CorpusChunkModel.id)
                    .filter(CorpusChunkModel.generation != generation)
                    .label("other_generation"),
                )
                .outerjoin(
                    CorpusChunkModel,
                    CorpusChunkModel.document_id == CorpusDocumentModel.id,
                )
                .where(index_filter)
                .group_by(CorpusDocumentModel.id)
                .order_by(CorpusDocumentModel.id)
            )
        ).all()

        pending_ids: list[uuid.UUID] = []
        active_ids: list[uuid.UUID] = []
        invalid_document = False
        for row in document_rows:
            total = int(row.total)
            staged = int(row.staged)
            active = int(row.active)
            valid = int(row.valid)
            if (
                total > 0
                and staged == total
                and valid == total
                and row.active_generation is None
                and int(row.incompatible_active) == 0
                and int(row.other_generation) == 0
            ):
                pending_ids.append(row.id)
            elif (
                total > 0
                and active == total
                and valid == total
                and row.active_generation == generation
                and int(row.incompatible_active) == 0
                and int(row.other_generation) == 0
            ):
                active_ids.append(row.id)
            else:
                invalid_document = True

        chunk_counts = (
            await self._session.execute(
                select(
                    func.count(CorpusChunkModel.id).label("total"),
                    func.count(CorpusChunkModel.id)
                    .filter(CorpusChunkModel.state == "STAGED")
                    .label("staged"),
                    func.count(CorpusChunkModel.id)
                    .filter(CorpusChunkModel.state == "ACTIVE")
                    .label("active"),
                    func.count(CorpusChunkModel.id)
                    .filter(CorpusChunkModel.embedding.is_not(None))
                    .label("embedded"),
                )
                .join(
                    CorpusDocumentModel,
                    CorpusDocumentModel.id == CorpusChunkModel.document_id,
                )
                .where(index_filter)
            )
        ).one()
        holdout_documents = int(
            await self._session.scalar(
                select(func.count())
                .select_from(CorpusDocumentModel)
                .where(
                    CorpusDocumentModel.metadata_json["evaluation_split"].as_string()
                    == "HOLDOUT_10"
                )
            )
            or 0
        )
        holdout_chunks = int(
            await self._session.scalar(
                select(func.count())
                .select_from(CorpusChunkModel)
                .join(
                    CorpusDocumentModel,
                    CorpusDocumentModel.id == CorpusChunkModel.document_id,
                )
                .where(
                    or_(
                        CorpusDocumentModel.metadata_json["evaluation_split"].as_string()
                        == "HOLDOUT_10",
                        CorpusChunkModel.metadata_json["evaluation_split"].as_string()
                        == "HOLDOUT_10",
                    )
                )
            )
            or 0
        )
        violations: list[str] = []
        if holdout_documents or holdout_chunks:
            violations.append("CORPUS_ACTIVATION_HOLDOUT_DETECTED")
        if invalid_document:
            violations.append("CORPUS_ACTIVATION_INVARIANT_FAILED")
        if not document_rows:
            violations.append("CORPUS_ACTIVATION_EMPTY_INDEX")

        return CorpusActivationSnapshot(
            database_name=database_name,
            generation=generation,
            documents_total=len(document_rows),
            documents_pending=len(pending_ids),
            documents_active=len(active_ids),
            chunks_total=int(chunk_counts.total or 0),
            chunks_staged=int(chunk_counts.staged or 0),
            chunks_active=int(chunk_counts.active or 0),
            embeddings_present=int(chunk_counts.embedded or 0),
            candidate_document_ids=tuple(pending_ids + active_ids),
            review_version_checksum=sum(
                int(row.review_version) for row in document_rows
            ),
            violations=tuple(sorted(violations)),
        )

    async def lock_document(
        self, document_id: uuid.UUID, *, generation: int
    ) -> CorpusActivationDocument:
        states = await self.lock_documents((document_id,), generation=generation)
        return states[0]

    async def lock_documents(
        self, document_ids: Sequence[uuid.UUID], *, generation: int
    ) -> tuple[CorpusActivationDocument, ...]:
        ids = tuple(sorted(set(document_ids), key=str))
        if not ids:
            return ()
        documents = (
            await self._session.execute(
                select(
                    CorpusDocumentModel.id,
                    CorpusDocumentModel.active_generation,
                    CorpusDocumentModel.metadata_json,
                )
                .where(CorpusDocumentModel.id.in_(ids))
                .order_by(CorpusDocumentModel.id)
                .with_for_update()
            )
        ).all()
        valid_embedding = self._embedding_is_valid()
        chunk_rows = (
            await self._session.execute(
                select(
                    CorpusChunkModel.document_id,
                    func.count(CorpusChunkModel.id)
                    .filter(CorpusChunkModel.generation == generation)
                    .label("total"),
                    func.count(CorpusChunkModel.id)
                    .filter(
                        and_(
                            CorpusChunkModel.generation == generation,
                            CorpusChunkModel.state == "STAGED",
                        )
                    )
                    .label("staged"),
                    func.count(CorpusChunkModel.id)
                    .filter(
                        and_(
                            CorpusChunkModel.generation == generation,
                            CorpusChunkModel.state == "ACTIVE",
                        )
                    )
                    .label("active"),
                    func.count(CorpusChunkModel.id)
                    .filter(
                        and_(
                            CorpusChunkModel.generation == generation,
                            valid_embedding,
                        )
                    )
                    .label("valid"),
                    func.count(CorpusChunkModel.id)
                    .filter(CorpusChunkModel.generation != generation)
                    .label("other_generation"),
                )
                .where(CorpusChunkModel.document_id.in_(ids))
                .group_by(CorpusChunkModel.document_id)
            )
        ).all()
        chunks_by_document = {row.document_id: row for row in chunk_rows}
        documents_by_id = {row.id: row for row in documents}
        result: list[CorpusActivationDocument] = []
        for document_id in ids:
            document = documents_by_id.get(document_id)
            chunks = chunks_by_document.get(document_id)
            state: Literal["STAGED", "ACTIVE", "INVALID"] = "INVALID"
            if (
                document is not None
                and document.metadata_json.get("evaluation_split") == "INDEX_90"
                and chunks is not None
                and int(chunks.total) > 0
                and int(chunks.valid) == int(chunks.total)
                and int(chunks.other_generation) == 0
            ):
                if (
                    document.active_generation is None
                    and int(chunks.staged) == int(chunks.total)
                ):
                    state = "STAGED"
                elif (
                    document.active_generation == generation
                    and int(chunks.active) == int(chunks.total)
                ):
                    state = "ACTIVE"
            result.append(
                CorpusActivationDocument(document_id=document_id, state=state)
            )
        return tuple(result)
