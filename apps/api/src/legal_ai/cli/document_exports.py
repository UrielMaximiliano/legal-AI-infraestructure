"""Entry point reserved for the 004 document-export administration CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.reconcile_service import ReconcileService
from legal_ai.domain.errors import CleanupConflictError, DomainError, FilesystemError


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser without executing cleanup operations."""
    parser = argparse.ArgumentParser(prog="document-exports")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--actor", required=True)
    reconcile.add_argument("--run-id", type=UUID)
    reconcile.add_argument("--execute", action="store_true")
    reconcile.add_argument("--case-file-id", type=UUID)
    reconcile.add_argument("--draft-id", type=UUID)
    reconcile.add_argument("--format", choices=("DOCX", "PDF"))
    reconcile.add_argument(
        "--incident-type",
        choices=(
            "TEMPORARY_FILE",
            "ORPHAN_FILE",
            "FAILED_ATTEMPT",
            "MISSING_FILE",
            "CORRUPT_FILE",
            "INCOMPLETE_DB",
        ),
    )
    reconcile.add_argument("--older-than")
    return parser


async def _run_reconcile(args: argparse.Namespace) -> int:
    async with UnitOfWork() as uow:
        result = await ReconcileService(uow).reconcile(
            actor=args.actor,
            run_id=args.run_id,
            execute=args.execute,
            case_file_id=args.case_file_id,
            draft_id=args.draft_id,
            format=args.format,
            incident_type=args.incident_type,
            older_than=args.older_than,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    """Execute the manual reconcile command and return its documented code."""
    args = build_parser().parse_args()
    try:
        if args.command == "reconcile":
            return asyncio.run(_run_reconcile(args))
    except CleanupConflictError as exc:
        print(
            json.dumps(
                {"error": {"code": exc.code, "message": exc.message}},
                ensure_ascii=False,
            )
        )
        return 2
    except (FilesystemError, OSError) as exc:
        del exc
        print(
            json.dumps(
                {
                    "error": {
                        "code": "EXPORT_STORAGE_UNAVAILABLE",
                        "message": "El storage de exportaciones no estÃ¡ disponible",
                    }
                },
                ensure_ascii=False,
            )
        )
        return 4
    except DomainError as exc:
        print(
            json.dumps(
                {"error": {"code": exc.code, "message": exc.message}},
                ensure_ascii=False,
            )
        )
        return 2
    return 2
