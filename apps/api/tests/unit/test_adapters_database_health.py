"""Unit tests for PostgreSQLHealthAdapter with mocked engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from legal_ai.adapters.database.health import PostgreSQLHealthAdapter
from legal_ai.domain.health import HealthStatus


@pytest.fixture
def adapter() -> PostgreSQLHealthAdapter:
    mock_engine = MagicMock()
    return PostgreSQLHealthAdapter(engine=mock_engine)


class TestCheck:
    @pytest.mark.anyio
    async def test_healthy(self, adapter: PostgreSQLHealthAdapter) -> None:
        version_result = MagicMock()
        version_result.fetchone.return_value = ("PostgreSQL 16.0",)

        pgvector_result = MagicMock()
        pgvector_result.fetchone.return_value = ("vector",)

        conn = AsyncMock()
        call_count = 0

        async def mock_execute(sql):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return version_result
            return pgvector_result

        conn.execute = mock_execute

        adapter._engine.connect = MagicMock()
        adapter._engine.connect.return_value.__aenter__ = AsyncMock(return_value=conn)
        adapter._engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.check()

        assert result.status == HealthStatus.OK
        assert result.latency_ms is not None

    @pytest.mark.anyio
    async def test_pgvector_missing(self, adapter: PostgreSQLHealthAdapter) -> None:
        version_result = MagicMock()
        version_result.fetchone.return_value = ("PostgreSQL 16.0",)

        pgvector_result = MagicMock()
        pgvector_result.fetchone.return_value = None

        conn = AsyncMock()
        call_count = 0

        async def mock_execute(sql):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return version_result
            return pgvector_result

        conn.execute = mock_execute

        adapter._engine.connect = MagicMock()
        adapter._engine.connect.return_value.__aenter__ = AsyncMock(return_value=conn)
        adapter._engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.check()

        assert result.status == HealthStatus.MISSING
        assert result.error_code == "PGVECTOR_MISSING"

    @pytest.mark.anyio
    async def test_connection_refused(self, adapter: PostgreSQLHealthAdapter) -> None:
        adapter._engine.connect = MagicMock()
        adapter._engine.connect.return_value.__aenter__ = AsyncMock(
            side_effect=OperationalError("connection refused", {}, None)
        )
        adapter._engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.check()

        assert result.status == HealthStatus.UNAVAILABLE
        assert result.error_code == "POSTGRES_UNAVAILABLE"

    @pytest.mark.anyio
    async def test_timeout(self, adapter: PostgreSQLHealthAdapter) -> None:
        adapter._engine.connect = MagicMock()
        adapter._engine.connect.return_value.__aenter__ = AsyncMock(
            side_effect=DBAPIError("timeout occurred", {}, None)
        )
        adapter._engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.check()

        assert result.status == HealthStatus.TIMEOUT
        assert result.error_code == "POSTGRES_UNAVAILABLE"

    @pytest.mark.anyio
    async def test_generic_db_error(self, adapter: PostgreSQLHealthAdapter) -> None:
        adapter._engine.connect = MagicMock()
        adapter._engine.connect.return_value.__aenter__ = AsyncMock(
            side_effect=DBAPIError("db error", {}, None)
        )
        adapter._engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.check()

        assert result.status == HealthStatus.UNAVAILABLE
