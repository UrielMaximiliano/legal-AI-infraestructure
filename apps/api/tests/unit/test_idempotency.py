"""Deterministic idempotency-window tests for draft generation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from legal_ai.application.draft_service import (
    DraftService,
    GenerationInProgressError,
    IdempotencyKeyMismatchError,
)
from legal_ai.application.ollama_client import OllamaResponse
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus, GenerationStatus
from legal_ai.domain.generation_attempt import GenerationAttempt
from tests.unit.test_draft_service import _uow


def _attempt(
    service: DraftService,
    template_id: uuid.UUID,
    case_file_id: uuid.UUID,
    *,
    status: GenerationStatus,
    key: str = "idem-key",
    created_at: datetime | None = None,
) -> GenerationAttempt:
    now = created_at or datetime.now(UTC)
    return GenerationAttempt(
        id=uuid.uuid4(),
        case_file_id=case_file_id,
        template_id=template_id,
        idempotency_key=key,
        model="test",
        prompt_hash=service._request_hash(
            str(template_id), str(case_file_id), {"note": "valor"}
        ),
        prompt_content="private prompt",
        status=status,
        started_at=now,
        created_at=now,
    )


def _cached_draft(attempt: GenerationAttempt) -> Draft:
    now = datetime.now(UTC)
    return Draft(
        id=uuid.uuid4(),
        template_id=attempt.template_id,
        case_file_id=attempt.case_file_id,
        title="Cached",
        content="cached result",
        status=DraftStatus.GENERADO,
        version=1,
        generation_number=1,
        context_snapshot={"metadata": {"attempt_id": str(attempt.id)}},
        context_hash="a" * 64,
        variables_used={"note": "valor"},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_same_key_same_payload_returns_cached_response() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    uow = _uow(template_id, case_file_id)
    service = DraftService(uow)
    existing = _attempt(
        service, template_id, case_file_id, status=GenerationStatus.COMPLETED
    )
    cached = _cached_draft(existing)
    uow.generation_attempts.get_by_idempotency_key.return_value = existing
    uow.drafts.list_by_case_file.return_value = ([cached], 1)
    service._ollama.generate = AsyncMock(side_effect=AssertionError("cache miss"))

    result = await service.generate_draft(
        str(template_id), str(case_file_id), {"note": "valor"}, "idem-key"
    )

    assert result.id == cached.id
    uow.drafts.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_key_different_payload_is_rejected() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    uow = _uow(template_id, case_file_id)
    service = DraftService(uow)
    uow.generation_attempts.get_by_idempotency_key.return_value = _attempt(
        service, template_id, case_file_id, status=GenerationStatus.COMPLETED
    )

    with pytest.raises(IdempotencyKeyMismatchError):
        await service.generate_draft(
            str(template_id), str(case_file_id), {"note": "distinto"}, "idem-key"
        )


@pytest.mark.asyncio
async def test_in_progress_key_returns_conflict() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    uow = _uow(template_id, case_file_id)
    service = DraftService(uow)
    uow.generation_attempts.get_by_idempotency_key.return_value = _attempt(
        service, template_id, case_file_id, status=GenerationStatus.IN_PROGRESS
    )

    with pytest.raises(GenerationInProgressError):
        await service.generate_draft(
            str(template_id), str(case_file_id), {"note": "valor"}, "idem-key"
        )


@pytest.mark.asyncio
async def test_failed_key_is_deleted_and_retry_is_allowed() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    uow = _uow(template_id, case_file_id)
    service = DraftService(uow)
    uow.generation_attempts.get_by_idempotency_key.return_value = _attempt(
        service, template_id, case_file_id, status=GenerationStatus.FAILED
    )
    service._ollama.generate = AsyncMock(
        return_value=OllamaResponse(content="retry result", model="test")
    )

    result = await service.generate_draft(
        str(template_id), str(case_file_id), {"note": "valor"}, "idem-key"
    )

    assert result.content == "retry result"
    uow.generation_attempts.delete_by_idempotency_key.assert_awaited_once_with(
        "idem-key"
    )
    assert uow.generation_attempts.create.await_count == 1


@pytest.mark.asyncio
async def test_key_older_than_24_hours_is_treated_as_new() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    uow = _uow(template_id, case_file_id)
    service = DraftService(uow)
    old = datetime.now(UTC) - timedelta(hours=24, seconds=1)
    uow.generation_attempts.get_by_idempotency_key.return_value = _attempt(
        service,
        template_id,
        case_file_id,
        status=GenerationStatus.IN_PROGRESS,
        created_at=old,
    )
    service._ollama.generate = AsyncMock(
        return_value=OllamaResponse(content="fresh result", model="test")
    )

    result = await service.generate_draft(
        str(template_id), str(case_file_id), {"note": "valor"}, "idem-key"
    )

    assert result.content == "fresh result"
    uow.generation_attempts.delete_by_idempotency_key.assert_awaited_once_with(
        "idem-key"
    )


@pytest.mark.asyncio
async def test_expiration_window_does_not_use_sleep() -> None:
    template_id, case_file_id = uuid.uuid4(), uuid.uuid4()
    uow = _uow(template_id, case_file_id)
    service = DraftService(uow)
    assert timedelta(hours=24) == service.IDEMPOTENCY_WINDOW
