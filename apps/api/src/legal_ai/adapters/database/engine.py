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

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
# ``get_session_factory`` may initialize the engine through ``get_engine``
# while holding this lock, so re-entrancy is required during first access.
_lock = threading.RLock()


def create_engine() -> AsyncEngine:
    """Crea un engine async aislado, dueño de su propio pool.

    Reservado para procesos autónomos (CLIs, migraciones de Alembic, tests de
    integración) que disponen el engine al terminar. La API usa
    :func:`get_engine` en su lugar.
    """

    return create_async_engine(
        settings.postgres.database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )


def get_engine() -> AsyncEngine:
    """Devuelve el engine compartido de la aplicación, creándolo una vez."""

    global _engine
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is None:
            _engine = create_async_engine(
                settings.postgres.database_url,
                poolclass=NullPool,
            )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Devuelve la factoría de sesiones ligada al engine compartido."""

    global _session_factory
    if _session_factory is not None:
        return _session_factory
    with _lock:
        if _session_factory is None:
            _session_factory = async_sessionmaker(
                get_engine(),
                expire_on_commit=False,
            )
    return _session_factory


async def dispose_engine() -> None:
    """Dispone el engine compartido; invocar sólo en el shutdown."""

    global _engine, _session_factory
    with _lock:
        engine, _engine = _engine, None
        _session_factory = None
    if engine is not None:
        await engine.dispose()
