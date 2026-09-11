"""Minimal focal tests for IMI template provenance and publication gates."""

from __future__ import annotations

import hashlib
import json
import uuid
from inspect import getsource
from pathlib import Path
from typing import Any

import pytest

from legal_ai.adapters.database.imi_core import ImiCoreRepository
from legal_ai.adapters.database.imi_template_bootstrap import bootstrap_sql
from legal_ai.application.template_management import (
    TEMPLATE_EXTRACTOR_VERSION,
    parser_candidates_to_safe,
    suggestions_to_candidates,
    validate_definition,
)
from legal_ai.domain.errors import (
    HumanReviewRequiredError,
    IdempotencyConflictError,
    TemplateDefinitionInvalidError,
    ValidationDomainError,
)


class _Mappings:
    def __init__(
        self,
        row: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self._row = row
        self._rows = rows or []

    def first(self) -> dict[str, Any] | None:
        return self._row

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _Result:
    def __init__(
        self,
        row: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
        scalar: Any = None,
    ) -> None:
        self._row = row
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self) -> _Mappings:
        return _Mappings(row=self._row, rows=self._rows)

    def scalar_one(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def first(self) -> Any:
        return self._row


class _FakeSession:
    """Minimal async session stub keyed by SQL fragments."""

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.idempotency: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self.queued: list[_Result] = []

    def queue(self, result: _Result) -> None:
        self.queued.append(result)

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        text_value = str(statement)
        self.executed.append(text_value)
        if "FROM imi.template_idempotency" in text_value:
            operation = str(params["operation"])
            key = str(params["key"])
            if text_value.lstrip().upper().startswith("SELECT"):
                stored = self.idempotency.get((operation, key))
                if stored is None:
                    return _Result(row=None)
                request_hash, response = stored
                return _Result(
                    row={"request_hash": request_hash, "response_json": response}
                )
            return _Result(row=None)
        if "INSERT INTO imi.template_idempotency" in text_value:
            operation = str(params["operation"])
            key = str(params["key"])
            self.idempotency[(operation, key)] = (
                str(params["request_hash"]),
                json.loads(str(params["response"])),
            )
            return _Result(row=None)
        if self.queued:
            return self.queued.pop(0)
        return _Result(row=None)


def _repo(session: Any) -> ImiCoreRepository:
    return ImiCoreRepository(session)


def test_extractor_version_is_pinned() -> None:
    assert TEMPLATE_EXTRACTOR_VERSION == "docx-parser-v1"


def test_parser_candidates_keep_bounded_marker_metadata() -> None:
    class _Candidate:
        original_text = "{{expediente}}"

        def to_safe_dict(self) -> dict[str, object]:
            return {
                "normalized_key": "expediente",
                "origin": "PARAGRAPH",
                "syntax": "DOUBLE_BRACE",
                "confidence": 0.95,
                "field_kind": "TEXT",
                "occurrences": 2,
            }

    safe = parser_candidates_to_safe([_Candidate()])
    assert safe[0]["key"] == "expediente"
    assert safe[0]["original_text"] == "{{expediente}}"
    assert safe[0]["occurrences"] == 2
    assert safe[0]["status"] == "confirmed"


def test_suggestions_fallback_has_no_pii() -> None:
    suggestions = [
        {
            "key": "nombre",
            "confidence": 0.82,
            "occurrences": [{"start": 0, "end": 4, "text": "____"}],
        }
    ]
    safe = suggestions_to_candidates(suggestions)
    assert safe[0]["key"] == "nombre"
    assert safe[0]["occurrences"] == 1
    assert safe[0]["fragment"] is None
    assert "text" not in safe[0]


def test_provenance_sha_is_deterministic() -> None:
    data = b"controlled-bytes"
    assert hashlib.sha256(data).hexdigest() != hashlib.sha256(b"other").hexdigest()
    assert len(hashlib.sha256(data).hexdigest()) == 64


def test_validation_blocks_invalid_definition() -> None:
    errors = validate_definition(
        name=" ",
        body="Hola {{inexistente}}",
        fields=[],
        rules=[{"type": "validation"}],
        blocks=None,
    )
    assert any("nombre" in error.lower() for error in errors)
    assert any("inexistente" in error for error in errors)


def test_import_response_schema_accepts_provenance() -> None:
    from legal_ai.schemas.template import TemplateImportResponse

    payload = TemplateImportResponse.model_validate(
        {
            "id": uuid.uuid4(),
            "status": "SUCCEEDED",
            "stage": "complete",
            "progress": 100,
            "pages_total": 1,
            "pages_processed": 1,
            "body_template": "Hola",
            "blocks": [],
            "warnings": [],
            "error": None,
            "retryable": False,
            "template_version": None,
            "source_sha256": "a" * 64,
            "source_size_bytes": 12,
            "extractor_version": TEMPLATE_EXTRACTOR_VERSION,
            "candidates": [
                {
                    "key": "nombre",
                    "origin": "PARAGRAPH",
                    "syntax": "BLANK",
                    "confidence": 0.55,
                    "field_kind": "TEXT",
                    "occurrences": 1,
                }
            ],
            "decisions": [{"key": "nombre", "status": "CONFIRMED"}],
            "decided_by": "revisor-imi",
            "decided_at": None,
        }
    )
    assert payload.source_sha256 == "a" * 64
    assert payload.candidates[0].key == "nombre"


def test_version_response_schema_accepts_provenance() -> None:
    from legal_ai.schemas.template import TemplateVersionResponse

    now = "2026-09-11T00:00:00Z"
    payload = TemplateVersionResponse.model_validate(
        {
            "id": uuid.uuid4(),
            "template_version_id": uuid.uuid4(),
            "version": 1,
            "status": "DRAFT",
            "revision": 1,
            "body_template": "Hola",
            "fields": [],
            "rules": [],
            "instructions": None,
            "blocks": [],
            "extraction_warnings": [],
            "created_at": now,
            "updated_at": now,
            "source_import_id": None,
            "source_sha256": None,
            "extractor_version": TEMPLATE_EXTRACTOR_VERSION,
        }
    )
    assert payload.extractor_version == TEMPLATE_EXTRACTOR_VERSION


def test_bootstrap_sql_is_non_destructive() -> None:
    sql_path = (
        Path(__file__).resolve().parents[4]
        / "infra"
        / "database"
        / "imi-core"
        / "init"
        / "005_template_import_provenance.sql"
    )
    if not sql_path.exists():
        sql_text = bootstrap_sql()
    else:
        sql_text = sql_path.read_text(encoding="utf-8")
    assert "IF NOT EXISTS" in sql_text
    assert "DROP TABLE" not in sql_text
    assert "source_sha256" in sql_text
    assert "candidates_json" in sql_text
    assert "decisions_json" in sql_text
    assert "TEMPLATE_VERSION_IMMUTABLE" in sql_text


def test_alembic_011_is_non_destructive() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "011_imi_template_import_provenance.py"
    )
    text = migration.read_text(encoding="utf-8")
    assert 'down_revision = "010"' in text
    assert "to_regclass" in text
    assert "DROP TABLE" not in text
    assert "DROP COLUMN" not in text


def test_template_routes_expose_full_docx_flow() -> None:
    from legal_ai.api.routes.templates import router, template_jobs_router

    paths: set[tuple[str, str]] = set()
    for holder in (router, template_jobs_router):
        for route in holder.routes:
            route_path: Any = getattr(route, "path", "")
            raw_methods: Any = getattr(route, "methods", set()) or set()
            for method in raw_methods:
                paths.add((str(route_path), str(method)))
    assert ("/api/v1/templates", "POST") in paths
    publish_path = "/api/v1/templates/{template_id}/versions/{version_id}/publish"
    assert (publish_path, "POST") in paths
    assert ("/api/v1/template-imports", "POST") in paths
    assert ("/api/v1/template-imports/{import_id}", "GET") in paths
    assert ("/api/v1/template-imports/{import_id}/decisions", "POST") in paths
    assert ("/api/v1/template-imports/{import_id}/promote", "POST") in paths
    assert ("/api/v1/template-validations", "POST") in paths


def test_human_actor_gate_rejects_automation() -> None:
    with pytest.raises(ValidationDomainError):
        ImiCoreRepository._require_human_actor("ai-bot-publisher")
    assert ImiCoreRepository._require_human_actor("revisor-imi") == "revisor-imi"


async def test_publish_requires_human_actor_before_db() -> None:
    session = _FakeSession()
    repo = _repo(session)
    with pytest.raises(ValidationDomainError):
        await repo.publish_template_version(
            template_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            revision=1,
            confirm_warnings=False,
            idempotency_key="k" * 16,
            request_hash="h" * 64,
            actor="ollama-model",
        )
    assert session.executed == []


async def test_publish_revision_conflict_is_409() -> None:
    from legal_ai.application.template_service import TemplateConflictError

    session = _FakeSession()
    repo = _repo(session)
    session.queue(
        _Result(
            row={
                "name": "Plantilla",
                "active": True,
                "body_template": "Hola",
                "status": "DRAFT",
                "revision": 2,
                "fields_json": [],
                "rules_json": [],
                "blocks_json": [],
                "extraction_warnings": [],
            }
        )
    )
    with pytest.raises(TemplateConflictError):
        await repo.publish_template_version(
            template_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            revision=1,
            confirm_warnings=True,
            idempotency_key=None,
            request_hash="h" * 64,
            actor="revisor-imi",
        )


async def test_publish_validation_blocks_without_confirmation() -> None:
    session = _FakeSession()
    repo = _repo(session)
    session.queue(
        _Result(
            row={
                "name": "Plantilla",
                "active": True,
                "body_template": "Hola",
                "status": "DRAFT",
                "revision": 1,
                "fields_json": [],
                "rules_json": [],
                "blocks_json": [],
                "extraction_warnings": ["tabla"],
            }
        )
    )
    with pytest.raises(TemplateDefinitionInvalidError):
        await repo.publish_template_version(
            template_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            revision=1,
            confirm_warnings=False,
            idempotency_key=None,
            request_hash="h" * 64,
            actor="revisor-imi",
        )


async def test_idempotent_publish_replay_returns_same_version() -> None:
    version_id = uuid.uuid4()
    template_id = uuid.uuid4()
    session = _FakeSession()
    repo = _repo(session)
    session.idempotency[("template-publish", "k" * 16)] = (
        "h" * 64,
        {"template_id": str(template_id), "template_version_id": str(version_id)},
    )

    async def _fake_version(
        template_id_arg: uuid.UUID, version_id_arg: uuid.UUID
    ) -> dict[str, Any] | None:
        assert template_id_arg == template_id
        assert version_id_arg == version_id
        return {"id": version_id, "status": "PUBLISHED"}

    repo.get_template_version = _fake_version  # type: ignore[assignment]
    version, created = await repo.publish_template_version(
        template_id=template_id,
        version_id=version_id,
        revision=1,
        confirm_warnings=True,
        idempotency_key="k" * 16,
        request_hash="h" * 64,
        actor="revisor-imi",
    )
    assert created is False
    assert version["status"] == "PUBLISHED"


async def test_idempotency_conflict_on_different_hash() -> None:
    session = _FakeSession()
    repo = _repo(session)
    session.idempotency[("template-publish", "k" * 16)] = (
        "a" * 64,
        {"template_id": str(uuid.uuid4())},
    )
    with pytest.raises(IdempotencyConflictError):
        await repo._idempotency_get("template-publish", "k" * 16, "b" * 64)


async def test_promote_requires_all_human_decisions() -> None:
    session = _FakeSession()
    repo = _repo(session)
    session.queue(
        _Result(
            row={
                "id": uuid.uuid4(),
                "name": "Plantilla",
                "document_type": "DISPOSICION",
                "body_template": "Hola",
                "blocks_json": [],
                "warnings_json": [],
                "candidates_json": [{"key": "nombre"}],
                "decisions_json": [],
                "source_sha256": "a" * 64,
                "source_size_bytes": 10,
                "extractor_version": TEMPLATE_EXTRACTOR_VERSION,
                "status": "SUCCEEDED",
            }
        )
    )
    with pytest.raises(HumanReviewRequiredError):
        await repo.promote_import_to_template(
            uuid.uuid4(),
            actor="revisor-imi",
            idempotency_key=None,
            request_hash="h" * 64,
        )


def test_immutable_reads_do_not_mutate() -> None:
    assert "UPDATE" not in getsource(ImiCoreRepository.get_template_version)
    assert "DELETE" not in getsource(ImiCoreRepository.get_template_version)
    assert "UPDATE" not in getsource(ImiCoreRepository.list_template_versions)
    assert "FOR UPDATE" not in getsource(ImiCoreRepository.get_template_version)


def test_core_repository_stays_isolated_from_legacy() -> None:
    source = getsource(ImiCoreRepository)
    assert "from legal_ai.adapters.database.models import" not in source
    from legal_ai.adapters.database.engine import get_session_factory

    assert (
        get_session_factory("core") is not get_session_factory("legacy")
    )


def test_service_token_middleware_is_fail_closed() -> None:
    from legal_ai.api.middleware import ServiceTokenMiddleware

    source = getsource(ServiceTokenMiddleware.dispatch)
    assert "SERVICE_AUTH_REQUIRED" in source
    assert "SERVICE_AUTH_INVALID" in source
