"""Constraint and index checks for 004."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from legal_ai.adapters.database.engine import create_engine


@pytest.mark.integration
async def test_004_constraints_and_partial_indexes() -> None:
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            constraints = set(
                (
                    await connection.execute(
                        text(
                            "SELECT conname FROM pg_constraint "
                            "WHERE conname LIKE 'ck_%' OR conname LIKE 'uq_%'"
                        )
                    )
                ).scalars()
            )
            assert {
                "uq_review_draft_version",
                "uq_export_draft_format_version",
                "uq_export_attempt_number",
                "uq_review_operation_request",
                "ck_export_attempt_status",
                "ck_export_status",
            } <= constraints

            indexes = set(
                (
                    await connection.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE schemaname = 'public'"
                        )
                    )
                ).scalars()
            )
            assert {
                "uq_exports_active_generation",
                "uq_export_attempt_active_actor_key",
                "uq_review_events_reconciliation_run",
            } <= indexes

            not_null = {
                row[0]: row[1]
                for row in (
                    await connection.execute(
                        text(
                            "SELECT column_name, is_nullable "
                            "FROM information_schema.columns "
                            "WHERE table_name = 'document_reviews' "
                            "AND column_name IN ("
                            "'review_snapshot', 'review_snapshot_sha256')"
                        )
                    )
                ).all()
            }
            assert not_null == {
                "review_snapshot": "NO",
                "review_snapshot_sha256": "NO",
            }

            delete_rule = await connection.scalar(
                text(
                    "SELECT delete_rule FROM "
                    "information_schema.referential_constraints "
                    "WHERE constraint_name = 'fk_review_events_attempt_id'"
                )
            )
            assert delete_rule == "SET NULL"
    finally:
        await engine.dispose()
