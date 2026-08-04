"""Contract checks for the administrative reconcile CLI."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from legal_ai.cli import document_exports
from legal_ai.domain.errors import (
    CleanupConflictError,
    FilesystemError,
    ValidationDomainError,
)


def test_reconcile_parser_requires_actor_and_accepts_contract_filters() -> None:
    args = document_exports.build_parser().parse_args(
        [
            "reconcile",
            "--actor",
            "admin@example",
            "--run-id",
            str(uuid4()),
            "--execute",
            "--format",
            "PDF",
            "--incident-type",
            "ORPHAN_FILE",
            "--older-than",
            "P7D",
        ]
    )
    assert args.command == "reconcile"
    assert args.execute is True
    assert args.format == "PDF"
    assert args.incident_type == "ORPHAN_FILE"


def test_reconcile_cli_emits_json_and_returns_success(monkeypatch, capsys) -> None:
    class FakeUow:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    class FakeService:
        def __init__(self, uow):
            self.uow = uow

        async def reconcile(self, **kwargs):
            assert kwargs["execute"] is False
            return {
                "run_id": str(uuid4()),
                "mode": "dry-run",
                "filters": {},
                "candidates": 0,
                "deleted": 0,
                "omitted": 0,
                "conflicts": 0,
                "errors": 0,
                "items": [],
            }

    monkeypatch.setattr(document_exports, "UnitOfWork", FakeUow)
    monkeypatch.setattr(document_exports, "ReconcileService", FakeService)
    monkeypatch.setattr(
        "sys.argv", ["document-exports", "reconcile", "--actor", "admin"]
    )
    assert document_exports.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"


def test_reconcile_cli_async_entrypoint_is_available() -> None:
    assert asyncio.iscoroutinefunction(document_exports._run_reconcile)


def test_reconcile_cli_returns_conflict_code(monkeypatch, capsys) -> None:
    async def fail(args):
        raise CleanupConflictError()

    monkeypatch.setattr(document_exports, "_run_reconcile", fail)
    monkeypatch.setattr(
        "sys.argv", ["document-exports", "reconcile", "--actor", "admin"]
    )
    assert document_exports.main() == 2
    assert "CLEANUP_CONFLICT" in capsys.readouterr().out


def test_reconcile_cli_returns_storage_code(monkeypatch, capsys) -> None:
    async def fail(args):
        raise FilesystemError()

    monkeypatch.setattr(document_exports, "_run_reconcile", fail)
    monkeypatch.setattr(
        "sys.argv", ["document-exports", "reconcile", "--actor", "admin"]
    )
    assert document_exports.main() == 4
    assert "EXPORT_STORAGE_UNAVAILABLE" in capsys.readouterr().out


def test_reconcile_cli_returns_argument_code(monkeypatch, capsys) -> None:
    async def fail(args):
        raise ValidationDomainError()

    monkeypatch.setattr(document_exports, "_run_reconcile", fail)
    monkeypatch.setattr(
        "sys.argv", ["document-exports", "reconcile", "--actor", "admin"]
    )
    assert document_exports.main() == 2
    assert "VALIDATION_ERROR" in capsys.readouterr().out
