"""Cross-database audit store for IMI LEG RAG.

The store intentionally uses two transactions and only opaque UUID references
between them.  It never creates a foreign key or a join across databases.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from legal_ai.adapters.database.dispositions_rag_unit_of_work import (
    DispositionsRagUnitOfWork,
)
from legal_ai.adapters.database.imi_core import ImiCoreUnitOfWork
from legal_ai.application.rag_generation import RagGenerationError, RagGenerationOutcome
from legal_ai.domain.rag import (
    RagGenerationRun,
    RagGenerationStatus,
    RagRetrievedSource,
    RagSourceDisposition,
)
from legal_ai.schemas.rag import RagStructuredDraft


class ImiRagAuditStore:
    """Persist retrieval audit in RAG and generated IMI documents in core.

    The secondary vector database may hold retrieval/run metadata, but never
    stores generated document JSON, drafts, templates or IMI output text.
    """

    profile_code = "imi_leg_06b"

    _DB_STATUS_BY_DOMAIN = {
        RagGenerationStatus.PENDING: "QUEUED",
        RagGenerationStatus.RETRIEVING: "RUNNING",
        RagGenerationStatus.GENERATING: "RUNNING",
        RagGenerationStatus.VALIDATING: "RUNNING",
        RagGenerationStatus.SUCCEEDED: "SUCCEEDED",
        RagGenerationStatus.FAILED: "FAILED",
        RagGenerationStatus.CANCELLED: "CANCELLED",
    }

    async def get_run(
        self, run_id: UUID
    ) -> tuple[RagGenerationRun, list[RagRetrievedSource]] | None:
        async with DispositionsRagUnitOfWork() as uow:
            result = await uow.session.execute(
                text(
                    """
                    SELECT gr.*, rr.core_case_file_id, rr.core_template_version_id,
                           rr.query_sha256
                    FROM rag.generation_runs gr
                    JOIN rag.retrieval_runs rr ON rr.id = gr.retrieval_run_id
                    WHERE gr.id = :run_id
                    """
                ),
                {"run_id": run_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            source_rows = await uow.session.execute(
                text(
                    """
                    SELECT r.retrieval_rank, r.similarity_score, r.selected,
                           c.id AS chunk_id, c.generation, c.section_type,
                           c.article_number, c.content_sha256 AS content_hash,
                           d.id AS document_id, d.external_id,
                           COALESCE(d.title, d.external_id) AS title,
                           d.publication_date, d.source_url
                    FROM rag.generation_runs gr
                    JOIN rag.retrieval_runs rr ON rr.id = gr.retrieval_run_id
                    JOIN rag.retrieval_results r ON r.retrieval_run_id = rr.id
                    JOIN rag.corpus_chunks c ON c.id = r.chunk_id
                    JOIN rag.corpus_document_versions v
                      ON v.id = c.document_version_id
                    JOIN rag.corpus_documents d ON d.id = v.document_id
                    WHERE gr.id = :run_id
                    ORDER BY r.retrieval_rank
                    """
                ),
                {"run_id": run_id},
            )
            sources: list[RagRetrievedSource] = []
            context_rank = 0
            for source_row in source_rows.mappings():
                selected = bool(source_row["selected"])
                if selected:
                    context_rank += 1
                sources.append(
                    RagRetrievedSource(
                        document_id=source_row["document_id"],
                        chunk_id=source_row["chunk_id"],
                        external_id=source_row["external_id"],
                        title=source_row["title"],
                        publication_date=(
                            source_row["publication_date"].isoformat()
                            if source_row["publication_date"] is not None
                            else None
                        ),
                        section_type=source_row["section_type"],
                        generation=source_row["generation"],
                        similarity_score=float(source_row["similarity_score"]),
                        retrieval_rank=source_row["retrieval_rank"],
                        citation_id=f"SRC-{source_row['retrieval_rank']:03d}",
                        excerpt="",
                        article_number=source_row["article_number"],
                        source_url=source_row["source_url"],
                        disposition=(
                            RagSourceDisposition.SELECTED
                            if selected
                            else RagSourceDisposition.EXCLUDED_DIVERSITY
                        ),
                        context_rank=context_rank if selected else None,
                        content_hash=source_row["content_hash"],
                    )
                )
        template_id = UUID(int=0)
        case_file_id = row["core_case_file_id"] or UUID(int=0)
        if row["core_document_id"] is not None:
            async with ImiCoreUnitOfWork() as core_uow:
                draft = (
                    await core_uow.core.get_draft(row["core_document_id"])
                    if core_uow.core
                    else None
                )
            if draft is not None:
                template_id = draft.template_id
                case_file_id = draft.case_file_id
        if template_id.int == 0 or case_file_id.int == 0:
            return None
        return self._to_domain(row, template_id, case_file_id), sources

    async def reserve(
        self, key_hash: str, request_hash: str
    ) -> RagGenerationOutcome | None:
        async with DispositionsRagUnitOfWork() as uow:
            result = await uow.session.execute(
                text(
                    """
                    SELECT * FROM rag.generation_runs
                    WHERE idempotency_key_hash = :key_hash
                    ORDER BY started_at DESC LIMIT 1
                    """
                ),
                {"key_hash": key_hash},
            )
            row = result.mappings().first()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise RagGenerationError("RAG_IDEMPOTENCY_KEY_MISMATCH")
        status = _domain_status(row["status_code"])
        if status in {RagGenerationStatus.FAILED, RagGenerationStatus.CANCELLED}:
            return None
        if status is not RagGenerationStatus.SUCCEEDED:
            raise RagGenerationError("RAG_GENERATION_IN_PROGRESS")
        document_id = row["core_document_id"]
        if document_id is None:
            raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
        async with ImiCoreUnitOfWork() as core_uow:
            draft = (
                await core_uow.core.get_draft(document_id)
                if core_uow.core
                else None
            )
        content = draft.document if draft is not None else None
        if draft is None or not isinstance(content, dict):
            raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
        structured = RagStructuredDraft.model_validate(content)
        run = self._to_domain(row, draft.template_id, draft.case_file_id)
        return RagGenerationOutcome(run, structured, draft, tuple())

    async def create(self, run: RagGenerationRun) -> None:
        try:
            async with DispositionsRagUnitOfWork() as uow:
                ids = await uow.session.execute(
                    text(
                        """
                        SELECT
                          (SELECT id FROM rag.document_types
                           WHERE code = 'DECRETO') AS document_type_id,
                          (SELECT id FROM rag.jurisdictions
                           WHERE code = 'NACION') AS jurisdiction_id,
                          NULL::uuid AS organization_id,
                          (SELECT id FROM rag.embedding_models
                           WHERE model_name = :embedding_model) AS embedding_model_id
                        """
                    ),
                    {"embedding_model": run.embedding_model},
                )
                catalogs = ids.mappings().one()
                if any(
                    catalogs[key] is None
                    for key in (
                        "document_type_id",
                        "jurisdiction_id",
                        "embedding_model_id",
                    )
                ):
                    raise RagGenerationError("RAG_PROFILE_NOT_READY")
                await uow.session.execute(
                    text(
                        """
                        INSERT INTO rag.retrieval_runs (
                          id, core_case_file_id, core_template_version_id,
                          document_type_id, jurisdiction_id, organization_id,
                          language_code, required_review_status_code,
                          required_split_code, query_sha256, top_k,
                          candidate_pool_size, minimum_score, status_code,
                          request_id
                        ) VALUES (
                          :id, :case_file_id, NULL, :document_type_id,
                          :jurisdiction_id, :organization_id, 'es', 'REVIEWED',
                          'INDEX_90', :query_hash, :top_k, :candidate_pool_size,
                          :minimum_score, 'QUEUED', :request_id
                        )
                        """
                    ),
                    {
                        "id": run.id,
                        "case_file_id": run.case_file_id,
                        "document_type_id": catalogs["document_type_id"],
                        "jurisdiction_id": catalogs["jurisdiction_id"],
                        "organization_id": catalogs["organization_id"],
                        "query_hash": run.query_hash,
                        "top_k": run.top_k,
                        "candidate_pool_size": run.candidate_pool_size,
                        "minimum_score": run.minimum_score or 0,
                        "request_id": run.request_id,
                    },
                )
                await uow.session.execute(
                    text(
                        """
                        INSERT INTO rag.generation_runs (
                          id, retrieval_run_id, status_code, embedding_model_id,
                          generation_model, prompt_version, schema_version,
                          request_hash, idempotency_key_hash, profile_code,
                          request_id
                        ) VALUES (
                          :id, :retrieval_run_id, 'QUEUED', :embedding_model_id,
                          :generation_model, :prompt_version, :schema_version,
                          :request_hash, :idempotency_key_hash, :profile_code,
                          :request_id
                        )
                        """
                    ),
                    {
                        "id": run.id,
                        "retrieval_run_id": run.id,
                        "embedding_model_id": catalogs["embedding_model_id"],
                        "generation_model": run.generation_model,
                        "prompt_version": run.prompt_version,
                        "schema_version": run.schema_version,
                        "request_hash": run.request_hash,
                        "idempotency_key_hash": run.idempotency_key_hash,
                        "profile_code": run.profile_code,
                        "request_id": run.request_id,
                    },
                )
        except IntegrityError as exc:
            raise RagGenerationError("RAG_GENERATION_IN_PROGRESS") from exc

    async def update(self, run: RagGenerationRun) -> None:
        async with DispositionsRagUnitOfWork() as uow:
            await uow.session.execute(
                text(
                    """
                    UPDATE rag.generation_runs
                    SET status_code = :status_code,
                        context_hash = :context_hash,
                        prompt_hash = :prompt_hash,
                        retrieved_count = :retrieved_count,
                        selected_count = :selected_count,
                        context_bytes = :context_bytes,
                        context_tokens_estimate = :context_tokens_estimate,
                        schema_repair_count = :schema_repair_count,
                        retrieval_duration_ms = :retrieval_duration_ms,
                        generation_duration_ms = :generation_duration_ms,
                        validation_duration_ms = :validation_duration_ms,
                        total_duration_ms = :total_duration_ms,
                        core_document_id = :core_document_id,
                        core_document_version_id = :core_document_version_id,
                        error_code = :error_code,
                        finished_at = :finished_at,
                        updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                {
                    "id": run.id,
                    "status_code": self._DB_STATUS_BY_DOMAIN[run.status],
                    "context_hash": run.context_hash,
                    "prompt_hash": run.prompt_hash,
                    "retrieved_count": run.retrieved_count,
                    "selected_count": run.selected_count,
                    "context_bytes": run.context_bytes,
                    "context_tokens_estimate": run.context_tokens_estimate,
                    "schema_repair_count": run.schema_repair_count,
                    "retrieval_duration_ms": run.retrieval_duration_ms,
                    "generation_duration_ms": run.generation_duration_ms,
                    "validation_duration_ms": run.validation_duration_ms,
                    "total_duration_ms": run.total_duration_ms,
                    "core_document_id": run.draft_id,
                    "core_document_version_id": None,
                    "error_code": run.error_code,
                    "finished_at": run.finished_at,
                    "updated_at": run.updated_at,
                },
            )

    async def create_sources(
        self, run_id: UUID, sources: Sequence[Any]
    ) -> None:
        async with DispositionsRagUnitOfWork() as uow:
            for source in sources:
                selected = source.disposition is RagSourceDisposition.SELECTED
                await uow.session.execute(
                    text(
                        """
                        INSERT INTO rag.retrieval_results (
                          retrieval_run_id, chunk_id, retrieval_rank,
                          similarity_score, selected, exclusion_reason
                        ) VALUES (:run_id, :chunk_id, :rank, :score, :selected, :reason)
                        ON CONFLICT (retrieval_run_id, chunk_id) DO NOTHING
                        """
                    ),
                    {
                        "run_id": run_id,
                        "chunk_id": source.chunk_id,
                        "rank": source.retrieval_rank,
                        "score": source.similarity_score,
                        "selected": selected,
                        "reason": None if selected else source.disposition.value,
                    },
                )
            await uow.session.execute(
                text(
                    """
                    UPDATE rag.retrieval_runs
                    SET status_code = 'SUCCEEDED', retrieved_count = :retrieved_count,
                        selected_count = :selected_count, finished_at = now()
                    WHERE id = :id
                    """
                ),
                {
                    "id": run_id,
                    "retrieved_count": len(sources),
                    "selected_count": sum(
                        source.disposition is RagSourceDisposition.SELECTED
                        for source in sources
                    ),
                },
            )

    async def save_outcome(self, key_hash: str, outcome: RagGenerationOutcome) -> None:
        del key_hash
        if outcome.draft is None or outcome.structured_draft is None:
            raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
        async with ImiCoreUnitOfWork() as core_uow:
            if core_uow.core is None:
                raise RagGenerationError("RAG_AUDIT_UNAVAILABLE")
            draft_id, version_id = await core_uow.core.save_generation_outcome(
                outcome, request_id=outcome.run.request_id
            )
        async with DispositionsRagUnitOfWork() as uow:
            await uow.session.execute(
                text(
                    """
                    UPDATE rag.generation_runs
                    SET status_code = 'SUCCEEDED', core_document_id = :document_id,
                        core_document_version_id = :version_id,
                        finished_at = :finished_at,
                        updated_at = :finished_at
                    WHERE id = :run_id
                    """
                ),
                {
                    "run_id": outcome.run.id,
                    "document_id": draft_id,
                    "version_id": version_id,
                    "finished_at": outcome.run.finished_at or datetime.now(UTC),
                },
            )
            # Generated JSON is intentionally not written to the vector DB.

    @staticmethod
    def _to_domain(row: Any, template_id: UUID, case_file_id: UUID) -> RagGenerationRun:
        return RagGenerationRun(
            id=row["id"],
            case_file_id=case_file_id,
            template_id=template_id,
            request_hash=row["request_hash"],
            query_hash=(
                row["query_hash"]
                if "query_hash" in row
                else row["request_hash"]
            ),
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=1024,
            profile_code="imi_leg_06b",
            generation_model=row["generation_model"],
            prompt_version=row["prompt_version"],
            schema_version=row["schema_version"],
            top_k=8,
            candidate_pool_size=24,
            status=_domain_status(row["status_code"]),
            request_id=row["request_id"],
            created_at=row["started_at"],
            updated_at=row.get("updated_at") or row["started_at"],
            finished_at=row["finished_at"],
            draft_id=row["core_document_id"],
            context_hash=row.get("context_hash"),
            prompt_hash=row.get("prompt_hash"),
            retrieved_count=row.get("retrieved_count") or 0,
            selected_count=row.get("selected_count") or 0,
        )


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _domain_status(value: str) -> RagGenerationStatus:
    """Translate audit persistence statuses to the richer application enum."""

    if value == "QUEUED":
        return RagGenerationStatus.PENDING
    if value == "RUNNING":
        return RagGenerationStatus.RETRIEVING
    return RagGenerationStatus(value)
