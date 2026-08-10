"""Named PostgreSQL generation E2E entry point for the feature task list."""

from __future__ import annotations

import pytest

from .test_rag_postgres_e2e import (
    test_postgres_generation_persists_review_and_replays_idempotently as _run,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_generation_persists_draft_review_and_audit() -> None:
    await _run()
