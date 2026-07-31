"""Aplicación FastAPI principal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from legal_ai.api.router import router
from legal_ai.config import settings
from legal_ai.observability.logging import setup_logging
from legal_ai.observability.request_context import RequestContextMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Gestión del lifespan de la aplicación."""
    setup_logging(settings.logging.level)
    yield


app = FastAPI(
    title=settings.app.name,
    version=settings.app.version,
    lifespan=lifespan,
)

app.add_middleware(RequestContextMiddleware)
app.include_router(router)
