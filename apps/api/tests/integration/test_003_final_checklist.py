"""Machine-checkable scope and final acceptance checklist for increment 003."""

from __future__ import annotations

from pathlib import Path

import pytest

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.ollama_client import OllamaResponse
from legal_ai.domain.draft import VALID_TRANSITIONS
from legal_ai.main import app
from tests.contract.helpers_003 import seed_case_and_template

EXPECTED_ENDPOINTS = {
    ("POST", "/api/v1/templates"),
    ("GET", "/api/v1/templates"),
    ("GET", "/api/v1/templates/{template_id}"),
    ("PATCH", "/api/v1/templates/{template_id}"),
    ("POST", "/api/v1/templates/{template_id}/deactivate"),
    ("POST", "/api/v1/case-files/{case_file_id}/designation"),
    ("GET", "/api/v1/case-files/{case_file_id}/designation"),
    ("PUT", "/api/v1/case-files/{case_file_id}/designation"),
    ("POST", "/api/v1/drafts/generate"),
    ("GET", "/api/v1/case-files/{case_file_id}/drafts"),
    ("GET", "/api/v1/drafts/{draft_id}"),
    ("PATCH", "/api/v1/drafts/{draft_id}/content"),
    ("POST", "/api/v1/drafts/{draft_id}/transitions"),
    ("POST", "/api/v1/drafts/{draft_id}/regenerate"),
    ("GET", "/api/v1/drafts/{draft_id}/history"),
    ("GET", "/api/v1/generation-attempts/{attempt_id}"),
    ("GET", "/api/v1/case-files/{case_file_id}/generation-attempts"),
}

ERROR_CODES = {
    "DOCUMENT_TEMPLATE_NOT_FOUND",
    "DOCUMENT_TEMPLATE_NAME_EXISTS",
    "DOCUMENT_TEMPLATE_INACTIVE",
    "DOCUMENT_TEMPLATE_CONFLICT",
    "CASE_FILE_NOT_FOUND",
    "DESIGNATION_DATA_NOT_FOUND",
    "DESIGNATION_DATA_INCOMPLETE",
    "CASE_FILE_TYPE_INCOMPATIBLE",
    "DRAFT_NOT_FOUND",
    "INVALID_DRAFT_TRANSITION",
    "DRAFT_ALREADY_APPROVED",
    "GENERATION_IN_PROGRESS",
    "GENERATION_FAILED",
    "OLLAMA_UNAVAILABLE",
    "OLLAMA_TIMEOUT",
    "CONCURRENT_MODIFICATION",
    "VALIDATION_ERROR",
    "DATABASE_ERROR",
    "MISSING_REQUIRED_VARIABLES",
    "CONTENT_TOO_LARGE",
    "CONTEXT_BUILD_FAILED",
    "IDEMPOTENCY_KEY_MISMATCH",
}


@pytest.mark.integration
def test_003_scope_and_endpoint_checklist() -> None:
    routes = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    assert len(EXPECTED_ENDPOINTS) == 17
    assert routes >= EXPECTED_ENDPOINTS
    assert not any(method == "DELETE" for method, _ in routes)
    assert not any(
        operation.get("security")
        for operations in app.openapi()["paths"].values()
        for operation in operations.values()
        if isinstance(operation, dict)
    )


@pytest.mark.integration
def test_003_error_state_and_excluded_scope_checklist() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "legal_ai"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in source_root.rglob("*.py")
    )
    assert {code for code in ERROR_CODES if code in source} >= ERROR_CODES
    assert sum(len(targets) for targets in VALID_TRANSITIONS.values()) == 4
    assert "context_snapshot" in source
    assert "prompt_content" in source
    assert not (source_root.parent.parent / "frontend").exists()
    forbidden_dirs = {
        # Incremento 005 intentionally adds the replaceable embeddings adapter.
        "redis",
        "pdf",
        "docx",
        "kubernetes",
        "terraform",
        "helm",
    }
    assert not any(
        path.name.lower() in forbidden_dirs for path in source_root.rglob("*")
    )


@pytest.mark.integration
async def test_003_context_snapshot_is_immutable_after_edit(monkeypatch):
    async def fake_generate(self, prompt):
        return OllamaResponse(content="generated", model="test")

    monkeypatch.setattr(
        "legal_ai.application.ollama_client.OllamaClient.generate", fake_generate
    )
    case_file_id, template_id = await seed_case_and_template()
    async with UnitOfWork() as uow:
        from legal_ai.application.draft_service import DraftService

        service = DraftService(uow)
        draft = await service.generate_draft(str(template_id), str(case_file_id))
        snapshot = draft.context_snapshot.copy()
        await service.transition_draft(
            str(draft.id), "send_to_review", expected_version=1
        )
        await service.edit_content(str(draft.id), "edited", expected_version=2)

    async with UnitOfWork() as uow:
        persisted = await uow.drafts.get_by_id(draft.id)
    assert persisted is not None
    assert persisted.context_snapshot == snapshot
