"""Unit tests for generation attempt."""

import uuid
from datetime import UTC, datetime

from legal_ai.domain.enums import GenerationStatus
from legal_ai.domain.generation_attempt import GenerationAttempt


class TestGenerationAttempt:
    def test_create_attempt(self):
        attempt = GenerationAttempt(
            id=uuid.uuid4(),
            case_file_id=uuid.uuid4(),
            template_id=uuid.uuid4(),
            model="llama3.1:8b",
            prompt_hash="abc123",
            prompt_content="test prompt",
            status=GenerationStatus.IN_PROGRESS,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        assert attempt.status == GenerationStatus.IN_PROGRESS
        assert attempt.model == "llama3.1:8b"
        assert attempt.prompt_content == "test prompt"

    def test_attempt_status_values(self):
        assert GenerationStatus.IN_PROGRESS == "in_progress"
        assert GenerationStatus.COMPLETED == "completed"
        assert GenerationStatus.FAILED == "failed"

    def test_attempt_with_idempotency_key(self):
        attempt = GenerationAttempt(
            id=uuid.uuid4(),
            case_file_id=uuid.uuid4(),
            template_id=uuid.uuid4(),
            model="llama3.1:8b",
            prompt_hash="abc",
            prompt_content="prompt",
            status=GenerationStatus.IN_PROGRESS,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            idempotency_key="key-123",
        )
        assert attempt.idempotency_key == "key-123"

    def test_attempt_with_error(self):
        attempt = GenerationAttempt(
            id=uuid.uuid4(),
            case_file_id=uuid.uuid4(),
            template_id=uuid.uuid4(),
            model="llama3.1:8b",
            prompt_hash="abc",
            prompt_content="prompt",
            status=GenerationStatus.FAILED,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            error_code="OLLAMA_UNAVAILABLE",
            error_message="Service unavailable",
            completed_at=datetime.now(UTC),
        )
        assert attempt.status == GenerationStatus.FAILED
        assert attempt.error_code == "OLLAMA_UNAVAILABLE"
