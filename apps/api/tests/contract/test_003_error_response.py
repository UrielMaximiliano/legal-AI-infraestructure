"""Contract tests for 003 error responses."""

import json
import uuid
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from legal_ai.api.exceptions import (
    conflict_error_handler,
    generic_error_handler,
    not_found_error_handler,
    service_error_handler,
    validation_error_handler,
)
from legal_ai.application.case_file_service import CaseFileNotFoundError
from legal_ai.application.designation_service import (
    CaseFileTypeIncompatibleError,
    DesignationNotFoundError,
)
from legal_ai.application.draft_service import (
    ConcurrentModificationError,
    ContentTooLargeError,
    DraftAlreadyApprovedError,
    DraftNotFoundError,
    GenerationInProgressError,
    IdempotencyKeyMismatchError,
    InvalidDraftTransitionError,
)
from legal_ai.application.generation_context import (
    ContextBuildFailedError,
    DesignationDataIncompleteError,
    MissingRequiredVariablesError,
)
from legal_ai.application.ollama_client import (
    GenerationFailedError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from legal_ai.application.template_service import (
    TemplateConflictError,
    TemplateInactiveError,
    TemplateNameConflictError,
    TemplateNotFoundError,
)
from legal_ai.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.contract
class TestErrorCodes:
    async def test_template_not_found_404(self, client):
        response = await client.get(f"/api/v1/templates/{uuid.uuid4()}")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "DOCUMENT_TEMPLATE_NOT_FOUND"
        assert "request_id" in data

    async def test_draft_not_found_404(self, client):
        response = await client.get(f"/api/v1/drafts/{uuid.uuid4()}")
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "DRAFT_NOT_FOUND"

    async def test_case_file_not_found_404(self, client):
        response = await client.get(f"/api/v1/case-files/{uuid.uuid4()}/drafts")
        assert response.status_code == 404

    async def test_validation_error_422(self, client):
        response = await client.get("/api/v1/templates/invalid-uuid")
        assert response.status_code == 422
        data = response.json()
        assert data["error_code"] == "VALIDATION_ERROR"

    async def test_no_secrets_in_error_response(self, client):
        response = await client.get(f"/api/v1/templates/{uuid.uuid4()}")
        data = response.json()
        error_str = str(data)
        assert "test-token" not in error_str
        assert "OLLAMA_API_TOKEN" not in error_str
        assert (
            "password" not in error_str.lower()
            or "password" in data.get("message", "").lower()
        )

    async def test_error_response_has_request_id(self, client):
        response = await client.get(f"/api/v1/templates/{uuid.uuid4()}")
        data = response.json()
        assert "request_id" in data

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("handler", "exc", "status", "code"),
        [
            (
                not_found_error_handler,
                TemplateNotFoundError(str(uuid.uuid4())),
                404,
                "DOCUMENT_TEMPLATE_NOT_FOUND",
            ),
            (
                conflict_error_handler,
                TemplateNameConflictError("n", "resolucion"),
                409,
                "DOCUMENT_TEMPLATE_NAME_EXISTS",
            ),
            (
                conflict_error_handler,
                TemplateInactiveError(str(uuid.uuid4())),
                409,
                "DOCUMENT_TEMPLATE_INACTIVE",
            ),
            (
                conflict_error_handler,
                TemplateConflictError(str(uuid.uuid4())),
                409,
                "DOCUMENT_TEMPLATE_CONFLICT",
            ),
            (
                not_found_error_handler,
                CaseFileNotFoundError(str(uuid.uuid4())),
                404,
                "CASE_FILE_NOT_FOUND",
            ),
            (
                not_found_error_handler,
                DesignationNotFoundError(str(uuid.uuid4())),
                404,
                "DESIGNATION_DATA_NOT_FOUND",
            ),
            (
                validation_error_handler,
                DesignationDataIncompleteError(),
                422,
                "DESIGNATION_DATA_INCOMPLETE",
            ),
            (
                conflict_error_handler,
                CaseFileTypeIncompatibleError(str(uuid.uuid4())),
                409,
                "CASE_FILE_TYPE_INCOMPATIBLE",
            ),
            (
                not_found_error_handler,
                DraftNotFoundError(str(uuid.uuid4())),
                404,
                "DRAFT_NOT_FOUND",
            ),
            (
                conflict_error_handler,
                InvalidDraftTransitionError("generado", "aprobado"),
                409,
                "INVALID_DRAFT_TRANSITION",
            ),
            (
                conflict_error_handler,
                DraftAlreadyApprovedError(str(uuid.uuid4())),
                409,
                "DRAFT_ALREADY_APPROVED",
            ),
            (
                conflict_error_handler,
                GenerationInProgressError("key"),
                409,
                "GENERATION_IN_PROGRESS",
            ),
            (service_error_handler, GenerationFailedError(), 502, "GENERATION_FAILED"),
            (
                service_error_handler,
                OllamaUnavailableError(),
                503,
                "OLLAMA_UNAVAILABLE",
            ),
            (service_error_handler, OllamaTimeoutError(), 504, "OLLAMA_TIMEOUT"),
            (
                conflict_error_handler,
                ConcurrentModificationError(str(uuid.uuid4())),
                409,
                "CONCURRENT_MODIFICATION",
            ),
            (
                generic_error_handler,
                RuntimeError("database details"),
                500,
                "DATABASE_ERROR",
            ),
            (
                validation_error_handler,
                MissingRequiredVariablesError(["position"]),
                422,
                "MISSING_REQUIRED_VARIABLES",
            ),
            (
                validation_error_handler,
                ContentTooLargeError(100001),
                422,
                "CONTENT_TOO_LARGE",
            ),
            (
                generic_error_handler,
                ContextBuildFailedError(),
                500,
                "CONTEXT_BUILD_FAILED",
            ),
            (
                conflict_error_handler,
                IdempotencyKeyMismatchError("key"),
                409,
                "IDEMPOTENCY_KEY_MISMATCH",
            ),
        ],
    )
    async def test_error_catalog_mapping(self, handler, exc, status, code):
        request = MagicMock()
        request.state.request_id = "req-catalog"
        response = await handler(request, exc)
        assert response.status_code == status
        payload = json.loads(response.body)
        assert payload["error_code"] == code
        assert payload["request_id"] == "req-catalog"
        assert "test-token" not in str(payload)

    async def test_validation_error_code_is_structured(self, client):
        response = await client.get("/api/v1/templates/not-a-uuid")
        assert response.status_code == 422
        payload = response.json()
        assert payload["error_code"] == "VALIDATION_ERROR"
        assert payload["request_id"]
