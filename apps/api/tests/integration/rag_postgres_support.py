"""Opt-in PostgreSQL support for destructive RAG integration fixtures."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator

import pytest
from sqlalchemy.engine import URL, make_url

from legal_ai.config import settings


def isolated_url() -> URL:
    value = os.environ.get("RAG_TEST_DATABASE_URL")
    if not value:
        pytest.skip("RAG_TEST_DATABASE_URL must point to an isolated test database")
    url = make_url(value)
    if url.database in {None, "", "legal_ai"}:
        pytest.fail("RAG_TEST_DATABASE_URL must name a dedicated database")
    if url.drivername != "postgresql+asyncpg":
        url = url.set(drivername="postgresql+asyncpg")
    return url


@pytest.fixture(autouse=True)
def configure_isolated_database() -> Iterator[URL]:
    url = isolated_url()
    if url.host is None or url.port is None or url.username is None:
        pytest.fail("RAG_TEST_DATABASE_URL must include host, port and user")
    settings.postgres.host = url.host
    settings.postgres.port = url.port
    settings.postgres.db = url.database or ""
    settings.postgres.user = url.username
    settings.postgres.password = url.password or ""
    yield url


def alembic_environment() -> dict[str, str]:
    url = isolated_url()
    return {
        "POSTGRES_HOST": str(url.host),
        "POSTGRES_PORT": str(url.port),
        "POSTGRES_DB": str(url.database),
        "POSTGRES_USER": str(url.username),
        "POSTGRES_PASSWORD": str(url.password or ""),
    }


def run_alembic(*arguments: str) -> None:
    url = isolated_url()
    settings.postgres.host = str(url.host)
    settings.postgres.port = url.port or 5432
    settings.postgres.db = str(url.database)
    settings.postgres.user = str(url.username)
    settings.postgres.password = url.password or ""
    environment = dict(os.environ)
    environment.update(alembic_environment())
    subprocess.run(
        ["uv", "run", "alembic", *arguments],
        cwd=__file__.split("tests")[0].rstrip("\\/"),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
