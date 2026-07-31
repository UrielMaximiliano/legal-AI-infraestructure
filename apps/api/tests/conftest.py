"""Fixtures compartidos para pruebas."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv


def _load_dotenv() -> None:
    """Carga .env del raíz del proyecto si existe."""
    env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


_load_dotenv()


@pytest.fixture(autouse=True)
def _set_test_env() -> None:
    """Configura variables de entorno para pruebas."""
    os.environ.setdefault("OLLAMA_BASE_URL", "http://test-host:11434")
    os.environ.setdefault("OLLAMA_API_TOKEN", "test-token-for-tests")
    os.environ.setdefault("POSTGRES_HOST", "localhost")
    os.environ.setdefault("POSTGRES_DB", "legal_ai")
    os.environ.setdefault("POSTGRES_USER", "legal_ai")
    os.environ.setdefault("POSTGRES_PASSWORD", "test-password")

    from legal_ai.config import settings

    settings.postgres.host = os.environ["POSTGRES_HOST"]
    settings.postgres.db = os.environ["POSTGRES_DB"]
    settings.postgres.user = os.environ["POSTGRES_USER"]
    settings.postgres.password = os.environ["POSTGRES_PASSWORD"]


@pytest.fixture
def anyio_backend() -> str:
    """Backend para pruebas async."""
    return "asyncio"
