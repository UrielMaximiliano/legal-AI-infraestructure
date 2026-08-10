from __future__ import annotations

import uuid

import pytest

from legal_ai.application.corpus_activation import CorpusActivationService
from legal_ai.domain.corpus import (
    CorpusActivationDocument,
    CorpusActivationSnapshot,
)
from legal_ai.schemas.corpus_activation import CorpusActivationRequest


def _snapshot(*, violations: tuple[str, ...] = ()) -> CorpusActivationSnapshot:
    document_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    return CorpusActivationSnapshot(
        database_name="isolated_test",
        generation=1,
        documents_total=1,
        documents_pending=1,
        documents_active=0,
        chunks_total=2,
        chunks_staged=2,
        chunks_active=0,
        embeddings_present=2,
        candidate_document_ids=(document_id,),
        review_version_checksum=1,
        violations=violations,
    )


def _active_snapshot() -> CorpusActivationSnapshot:
    document_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    return CorpusActivationSnapshot(
        database_name="isolated_test",
        generation=1,
        documents_total=1,
        documents_pending=0,
        documents_active=1,
        chunks_total=2,
        chunks_staged=0,
        chunks_active=2,
        embeddings_present=2,
        candidate_document_ids=(document_id,),
        review_version_checksum=1,
    )


class _ActivationRepository:
    def __init__(self, snapshot: CorpusActivationSnapshot) -> None:
        self.snapshot = snapshot

    async def inspect(self, *, generation: int) -> CorpusActivationSnapshot:
        assert generation == 1
        return self.snapshot

    async def lock_document(
        self, document_id: uuid.UUID, *, generation: int
    ) -> CorpusActivationDocument:
        assert generation == 1
        return CorpusActivationDocument(document_id=document_id, state="STAGED")

    async def lock_documents(
        self, document_ids: tuple[uuid.UUID, ...], *, generation: int
    ) -> tuple[CorpusActivationDocument, ...]:
        result: list[CorpusActivationDocument] = []
        for document_id in document_ids:
            result.append(
                await self.lock_document(document_id, generation=generation)
            )
        return tuple(result)


class _DocumentRepository:
    def __init__(self) -> None:
        self.swapped: list[uuid.UUID] = []
        self.processing: list[uuid.UUID] = []

    async def swap_generation(self, document_id: uuid.UUID, generation: int) -> None:
        self.swapped.append(document_id)

    async def update_processing_state(
        self, document_id: uuid.UUID, **kwargs: object
    ) -> None:
        assert kwargs == {
            "ingestion_status": "COMPLETED",
            "embedding_status": "EMBEDDED",
        }
        self.processing.append(document_id)

    async def swap_generations(
        self, document_ids: tuple[uuid.UUID, ...], generation: int
    ) -> None:
        for document_id in document_ids:
            await self.swap_generation(document_id, generation)

    async def update_processing_states(
        self, document_ids: tuple[uuid.UUID, ...], **kwargs: object
    ) -> None:
        for document_id in document_ids:
            await self.update_processing_state(document_id, **kwargs)


class _ChunkRepository:
    def __init__(self) -> None:
        self.activated: list[uuid.UUID] = []

    async def activate_generation(
        self, document_id: uuid.UUID, generation: int
    ) -> None:
        self.activated.append(document_id)

    async def activate_generations(
        self, document_ids: tuple[uuid.UUID, ...], generation: int
    ) -> None:
        for document_id in document_ids:
            await self.activate_generation(document_id, generation)


class _UnitOfWork:
    def __init__(self, snapshot: CorpusActivationSnapshot) -> None:
        self.corpus_activation = _ActivationRepository(snapshot)
        self.corpus_documents = _DocumentRepository()
        self.corpus_chunks = _ChunkRepository()
        self.rollbacks = 0

    async def __aenter__(self) -> _UnitOfWork:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_activation_dry_run_is_deterministic_and_has_zero_writes() -> None:
    snapshot = _snapshot()
    units: list[_UnitOfWork] = []

    def factory() -> _UnitOfWork:
        unit = _UnitOfWork(_active_snapshot() if len(units) >= 2 else snapshot)
        units.append(unit)
        return unit

    service = CorpusActivationService(uow_factory=factory)
    request = CorpusActivationRequest(expected_database="isolated_test")

    first = await service.dry_run(request)
    second = await service.dry_run(request)

    assert first == second
    assert first.execution_mode == "DRY_RUN"
    assert first.documents_activated == 0
    assert all(not unit.corpus_chunks.activated for unit in units)
    assert all(unit.rollbacks == 1 for unit in units)


@pytest.mark.asyncio
async def test_activation_fails_closed_before_any_write() -> None:
    snapshot = _snapshot(violations=("CORPUS_ACTIVATION_HOLDOUT_DETECTED",))
    unit = _UnitOfWork(snapshot)
    service = CorpusActivationService(uow_factory=lambda: unit)

    with pytest.raises(ValueError, match="CORPUS_ACTIVATION_PREFLIGHT_FAILED"):
        await service.execute(
            CorpusActivationRequest(expected_database="isolated_test")
        )

    assert unit.corpus_chunks.activated == []
    assert unit.corpus_documents.swapped == []


@pytest.mark.asyncio
async def test_activation_execute_reuses_contractual_repositories() -> None:
    snapshot = _snapshot()
    units: list[_UnitOfWork] = []

    def factory() -> _UnitOfWork:
        unit = _UnitOfWork(_active_snapshot() if len(units) >= 2 else snapshot)
        units.append(unit)
        return unit

    report = await CorpusActivationService(uow_factory=factory).execute(
        CorpusActivationRequest(expected_database="isolated_test")
    )

    transaction = units[1]
    document_id = snapshot.candidate_document_ids[0]
    assert transaction.corpus_chunks.activated == [document_id]
    assert transaction.corpus_documents.swapped == [document_id]
    assert transaction.corpus_documents.processing == [document_id]
    assert report.execution_mode == "EXECUTE"
    assert report.documents_activated == 1


@pytest.mark.asyncio
async def test_activation_resume_skips_already_active_documents() -> None:
    document_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    snapshot = _snapshot()

    class _AlreadyActive(_ActivationRepository):
        async def lock_document(
            self, document_id: uuid.UUID, *, generation: int
        ) -> CorpusActivationDocument:
            return CorpusActivationDocument(document_id=document_id, state="ACTIVE")

        async def lock_documents(
            self, document_ids: tuple[uuid.UUID, ...], *, generation: int
        ) -> tuple[CorpusActivationDocument, ...]:
            result: list[CorpusActivationDocument] = []
            for document_id in document_ids:
                result.append(
                    await self.lock_document(document_id, generation=generation)
                )
            return tuple(result)

    units: list[_UnitOfWork] = []

    def factory() -> _UnitOfWork:
        current_snapshot = _active_snapshot() if len(units) >= 2 else snapshot
        unit = _UnitOfWork(current_snapshot)
        unit.corpus_activation = _AlreadyActive(current_snapshot)
        units.append(unit)
        return unit

    report = await CorpusActivationService(uow_factory=factory).execute(
        CorpusActivationRequest(expected_database="isolated_test")
    )

    assert report.documents_activated == 0
    assert report.documents_already_active == 1
    assert units[1].corpus_chunks.activated == []
    assert document_id in snapshot.candidate_document_ids


@pytest.mark.asyncio
async def test_activation_rejects_database_identity_mismatch() -> None:
    service = CorpusActivationService(uow_factory=lambda: _UnitOfWork(_snapshot()))

    with pytest.raises(ValueError, match="CORPUS_ACTIVATION_DATABASE_MISMATCH"):
        await service.execute(
            CorpusActivationRequest(expected_database="operational_database")
        )
