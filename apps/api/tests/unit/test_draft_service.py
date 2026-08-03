"""Unit tests for the complete draft service workflow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from legal_ai.application.draft_service import (
    ConcurrentModificationError,
    DraftService,
    GenerationInProgressError,
    IdempotencyKeyMismatchError,
)
from legal_ai.application.ollama_client import (
    OllamaResponse,
    OllamaUnavailableError,
)
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import (
    DraftStatus,
    GenerationStatus,
    TemplateDocumentType,
)
from legal_ai.domain.generation_attempt import GenerationAttempt
from legal_ai.domain.template import Template


def _template(template_id: uuid.UUID) -> Template:
    now = datetime.now(UTC)
    return Template(
        id=template_id,
        name="Resolución",
        document_type=TemplateDocumentType.RESOLUCION,
        version=1,
        body_template="Empleado: {{employee.first_name}} {{variables.note}}",
        is_active=True,
        created_at=now,
        updated_at=now,
        variables=["note"],
    )


def _draft(
    template_id: uuid.UUID,
    case_file_id: uuid.UUID,
    *,
    status: DraftStatus = DraftStatus.EN_REVISION,
    version: int = 1,
) -> Draft:
    now = datetime.now(UTC)
    return Draft(
        id=uuid.uuid4(),
        template_id=template_id,
        case_file_id=case_file_id,
        title="Borrador",
        content="contenido",
        status=status,
        version=version,
        generation_number=1,
        context_snapshot={"metadata": {}},
        context_hash="a" * 64,
        variables_used={"note": "texto"},
        created_at=now,
        updated_at=now,
    )


def _uow(template_id: uuid.UUID, case_file_id: uuid.UUID) -> SimpleNamespace:
    employee_id = uuid.uuid4()
    repositories = {
        "templates": SimpleNamespace(
            get_by_id=AsyncMock(return_value=_template(template_id))
        ),
        "case_files": SimpleNamespace(
            get_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    id=case_file_id,
                    employee_id=employee_id,
                    case_number="EXP-1",
                    title="Expediente",
                    description=None,
                    case_type="otros",
                    status="draft",
                )
            )
        ),
        "employees": SimpleNamespace(
            get_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    id=employee_id,
                    first_name="Ana",
                    last_name="Pérez",
                    department="Legal",
                )
            )
        ),
        "designations": SimpleNamespace(get_by_case_file_id=AsyncMock()),
        "generation_attempts": SimpleNamespace(
            get_by_idempotency_key=AsyncMock(return_value=None),
            create=AsyncMock(side_effect=lambda value: value),
            update=AsyncMock(side_effect=lambda value: value),
            delete_by_idempotency_key=AsyncMock(),
        ),
        "drafts": SimpleNamespace(
            create=AsyncMock(side_effect=lambda value: value),
            get_by_id=AsyncMock(),
            list_by_case_file=AsyncMock(return_value=([], 0)),
            update=AsyncMock(),
            update_status=AsyncMock(),
            update_with_optimistic_lock=AsyncMock(),
        ),
        "draft_transitions": SimpleNamespace(
            create=AsyncMock(), list_by_draft=AsyncMock()
        ),
    }
    return SimpleNamespace(
        **repositories,
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_generate_success_commits_attempt_before_ollama() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    uow = _uow(template_id, case_file_id)
    service = DraftService(uow)

    async def generate(_: str) -> OllamaResponse:
        assert uow.commit.await_count == 1
        assert uow.drafts.create.await_count == 0
        return OllamaResponse(content="resultado", model="test")

    service._ollama.generate = AsyncMock(side_effect=generate)
    draft = await service.generate_draft(
        str(template_id), str(case_file_id), {"note": "texto"}, "key-1"
    )

    assert draft.content == "resultado"
    assert draft.status == DraftStatus.GENERADO
    assert uow.commit.await_count == 2


@pytest.mark.asyncio
async def test_ollama_failure_records_attempt_and_creates_no_draft() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    uow = _uow(template_id, case_file_id)
    service = DraftService(uow)
    service._ollama.generate = AsyncMock(side_effect=OllamaUnavailableError())

    with pytest.raises(OllamaUnavailableError):
        await service.generate_draft(str(template_id), str(case_file_id))

    uow.drafts.create.assert_not_awaited()
    failed = uow.generation_attempts.update.await_args.args[0]
    assert failed.status == GenerationStatus.FAILED
    assert failed.error_code == "OLLAMA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_idempotency_in_progress_and_mismatch() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    uow = _uow(template_id, case_file_id)
    service = DraftService(uow)
    request_hash = service._request_hash(str(template_id), str(case_file_id), {})
    attempt = GenerationAttempt(
        id=uuid.uuid4(),
        case_file_id=case_file_id,
        template_id=template_id,
        idempotency_key="same-key",
        model="test",
        prompt_hash=request_hash,
        prompt_content="prompt",
        status=GenerationStatus.IN_PROGRESS,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    uow.generation_attempts.get_by_idempotency_key.return_value = attempt

    with pytest.raises(GenerationInProgressError):
        await service.generate_draft(
            str(template_id), str(case_file_id), idempotency_key="same-key"
        )

    with pytest.raises(IdempotencyKeyMismatchError):
        await service.generate_draft(
            str(template_id),
            str(case_file_id),
            {"different": "payload"},
            "same-key",
        )


@pytest.mark.asyncio
async def test_regenerate_supersedes_only_after_success_with_lock() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    original = _draft(template_id, case_file_id)
    uow = _uow(template_id, case_file_id)
    uow.drafts.get_by_id.return_value = original
    uow.drafts.update.side_effect = lambda draft, expected: Draft(
        **{**draft.__dict__, "version": expected + 1}
    )
    service = DraftService(uow)

    async def generate(_: str) -> OllamaResponse:
        assert original.status == DraftStatus.EN_REVISION
        assert uow.drafts.update.await_count == 0
        return OllamaResponse(content="regenerado", model="test")

    service._ollama.generate = AsyncMock(side_effect=generate)
    regenerated = await service.regenerate_draft(str(original.id), 1)

    assert regenerated.parent_draft_id == original.id
    assert original.status == DraftStatus.SUPERSEDED
    assert uow.drafts.update.await_args.args[1] == 1
    transition = uow.draft_transitions.create.await_args.args[0]
    assert transition.from_status == DraftStatus.EN_REVISION
    assert transition.to_status == DraftStatus.SUPERSEDED


@pytest.mark.asyncio
async def test_regenerate_rolls_back_when_version_changes_during_ollama() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    original = _draft(template_id, case_file_id)
    uow = _uow(template_id, case_file_id)
    uow.drafts.get_by_id.return_value = original
    uow.drafts.update.return_value = None
    service = DraftService(uow)
    service._ollama.generate = AsyncMock(
        return_value=OllamaResponse(content="regenerado", model="test")
    )

    with pytest.raises(ConcurrentModificationError):
        await service.regenerate_draft(str(original.id), 1)

    uow.rollback.assert_awaited_once()
    uow.commit.assert_awaited_once()
