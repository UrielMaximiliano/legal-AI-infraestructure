"""Fail-closed orchestration for publishing already embedded corpus chunks."""

from __future__ import annotations

from typing import Any, Literal, cast

from legal_ai.domain.corpus import CorpusActivationSnapshot
from legal_ai.schemas.corpus_activation import (
    CorpusActivationReport,
    CorpusActivationRequest,
)


class CorpusActivationService:
    """Activate one generation using short, independently resumable transactions."""

    def __init__(self, *, uow_factory: Any) -> None:
        self._uow_factory = uow_factory

    async def _inspect(
        self, request: CorpusActivationRequest
    ) -> CorpusActivationSnapshot:
        try:
            async with self._uow_factory() as uow:
                snapshot = cast(
                    "CorpusActivationSnapshot",
                    await uow.corpus_activation.inspect(
                        generation=request.generation
                    ),
                )
                await uow.rollback()
        except Exception as exc:
            code = str(exc)
            if not code.startswith("CORPUS_"):
                code = "CORPUS_ACTIVATION_INSPECTION_FAILED"
            raise ValueError(code) from None
        if snapshot.database_name != request.expected_database:
            raise ValueError("CORPUS_ACTIVATION_DATABASE_MISMATCH")
        return snapshot

    @staticmethod
    def _assert_ready(snapshot: CorpusActivationSnapshot) -> None:
        if snapshot.violations:
            raise ValueError("CORPUS_ACTIVATION_PREFLIGHT_FAILED")
        if snapshot.documents_total != (
            snapshot.documents_pending + snapshot.documents_active
        ):
            raise ValueError("CORPUS_ACTIVATION_PREFLIGHT_FAILED")

    async def dry_run(
        self, request: CorpusActivationRequest
    ) -> CorpusActivationReport:
        snapshot = await self._inspect(request)
        self._assert_ready(snapshot)
        return self._report(snapshot, execution_mode="DRY_RUN", activated=0)

    async def execute(
        self, request: CorpusActivationRequest
    ) -> CorpusActivationReport:
        snapshot = await self._inspect(request)
        self._assert_ready(snapshot)
        activated = 0
        already_active = 0
        document_ids = snapshot.candidate_document_ids
        for start in range(0, len(document_ids), request.batch_size):
            batch = document_ids[start : start + request.batch_size]
            try:
                async with self._uow_factory() as uow:
                    states = await uow.corpus_activation.lock_documents(
                        batch, generation=request.generation
                    )
                    if len(states) != len(batch) or any(
                        current.state == "INVALID" for current in states
                    ):
                        raise ValueError("CORPUS_ACTIVATION_DOCUMENT_INVALID")
                    staged_ids = tuple(
                        current.document_id
                        for current in states
                        if current.state == "STAGED"
                    )
                    already_active += sum(
                        current.state == "ACTIVE" for current in states
                    )
                    await uow.corpus_chunks.activate_generations(
                        staged_ids, request.generation
                    )
                    await uow.corpus_documents.swap_generations(
                        staged_ids, request.generation
                    )
                    await uow.corpus_documents.update_processing_states(
                        staged_ids,
                        ingestion_status="COMPLETED",
                        embedding_status="EMBEDDED",
                    )
                    activated += len(staged_ids)
            except Exception as exc:
                code = str(exc)
                if not code.startswith("CORPUS_"):
                    code = "CORPUS_ACTIVATION_FAILED"
                raise ValueError(code) from None

        final_snapshot = await self._inspect(request)
        self._assert_ready(final_snapshot)
        if final_snapshot.documents_pending != 0:
            raise ValueError("CORPUS_ACTIVATION_INCOMPLETE")
        report = self._report(
            final_snapshot, execution_mode="EXECUTE", activated=activated
        )
        return report.model_copy(
            update={"documents_already_active": already_active}
        )

    @staticmethod
    def _report(
        snapshot: CorpusActivationSnapshot,
        *,
        execution_mode: Literal["DRY_RUN", "EXECUTE"],
        activated: int,
    ) -> CorpusActivationReport:
        return CorpusActivationReport(
            execution_mode=execution_mode,
            status="ready" if execution_mode == "DRY_RUN" else "completed",
            database_verified=True,
            generation=snapshot.generation,
            documents_total=snapshot.documents_total,
            documents_pending=snapshot.documents_pending,
            documents_activated=activated,
            documents_already_active=snapshot.documents_active,
            chunks_total=snapshot.chunks_total,
            chunks_staged=snapshot.chunks_staged,
            chunks_active=snapshot.chunks_active,
            embeddings_present=snapshot.embeddings_present,
            review_version_checksum=snapshot.review_version_checksum,
            violations=snapshot.violations,
        )
