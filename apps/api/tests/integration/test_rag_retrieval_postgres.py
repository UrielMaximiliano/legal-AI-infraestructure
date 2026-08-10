"""Named PostgreSQL retrieval E2E entry point for the feature task list."""

from __future__ import annotations

import pytest

from .test_rag_postgres_e2e import (
    test_postgres_retrieval_is_exact_and_fail_closed as _run,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_retrieval_uses_only_reviewed_index_90_active_chunks() -> None:
    await _run()
