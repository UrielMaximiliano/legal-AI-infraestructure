"""Named PostgreSQL holdout guard entry point for the feature task list."""

from __future__ import annotations

import pytest

from .test_rag_postgres_e2e import (
    test_postgres_holdout_guard_detects_operational_identity as _run,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_holdout_identity_is_rejected_by_operational_guard() -> None:
    await _run()
