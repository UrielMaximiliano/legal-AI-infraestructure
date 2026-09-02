"""SQLAlchemy async engine y sessionmaker con alcance de aplicación.

El engine compartido se crea una vez por proceso (lazy) y se dispone una sola
vez en el lifespan de la API. Ninguna operación individual crea o dispone
engines: :class:`UnitOfWork` sólo abre y cierra sesiones.

Se usa ``NullPool`` porque el ciclo actual abre sesiones cortas por operación
y así el engine compartido es seguro frente a múltiples event loops (tests,
scripts). El pooling por conexión sigue siendo responsabilidad del servidor.
"""

from __future__ import annotations

import threading

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from legal_ai.config import settings

_engines: dict[str, AsyncEngine] = {}
_session_factories: dict[str, async_sessionmaker[AsyncSession]] = {}
# ``get_session_factory`` may initialize the engine through ``get_engine``
# while holding this lock, so re-entrancy is required during first access.
_lock = threading.RLock()


def _database_url(database: str) -> str:
    if database == "legacy":
        return settings.postgres.database_url
    if database == "core":
        return settings.core_postgres.database_url
    if database == "imi_dispositions_rag":
        return settings.dispositions_rag_postgres.database_url
    raise ValueError("DATABASE_PROFILE_INVALID")


def create_engine(database: str = "legacy") -> AsyncEngine:
    """Crea un engine async aislado, dueño de su propio pool.

    Reservado para procesos autónomos (CLIs, migraciones de Alembic, tests de
    integración) que disponen el engine al terminar. La API usa
    :func:`get_engine` en su lugar.
    """

    return create_async_engine(
        _database_url(database),
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )


def get_engine(database: str = "legacy") -> AsyncEngine:
    """Devuelve el engine compartido de la aplicación, creándolo una vez."""

    engine = _engines.get(database)
    if engine is not None:
        return engine
    with _lock:
        engine = _engines.get(database)
        if engine is None:
            engine = create_async_engine(
                _database_url(database),
                poolclass=NullPool,
            )
            _engines[database] = engine
    return engine


def get_session_factory(database: str = "legacy") -> async_sessionmaker[AsyncSession]:
    """Devuelve la factoría de sesiones ligada al engine compartido."""

    factory = _session_factories.get(database)
    if factory is not None:
        return factory
    with _lock:
        factory = _session_factories.get(database)
        if factory is None:
            factory = async_sessionmaker(
                get_engine(database),
                expire_on_commit=False,
            )
            _session_factories[database] = factory
    return factory


async def dispose_engine() -> None:
    """Dispone el engine compartido; invocar sólo en el shutdown."""

    with _lock:
        engines = tuple(_engines.values())
        _engines.clear()
        _session_factories.clear()
    for engine in engines:
        await engine.dispose()
