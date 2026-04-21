"""
sky.core.db — SQLAlchemy async engine + session factory.

Usa las mismas tablas de Supabase. Cero migración de datos.
El engine se crea una vez al inicio del proceso y se reutiliza.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from sky.core.config import settings

# Construir URL asyncpg desde la URL de Supabase
# Supabase expone: https://xxx.supabase.co → la DB está en: postgresql://postgres:xxx@db.xxx.supabase.co:5432/postgres
# Para asyncpg necesitamos: postgresql+asyncpg://...
# En producción esto viene de una variable DATABASE_URL directa.
_engine = None
_session_factory = None


def _get_database_url() -> str:
    """
    Construye la URL de conexión.
    En producción: usar DATABASE_URL directa (más limpio).
    En dev: construir desde SUPABASE_URL si DATABASE_URL no existe.
    """
    import os
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        # Reemplazar postgresql:// por postgresql+asyncpg://
        return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Fallback: construir desde Supabase URL
    # NOTA: esto requiere que el dev configure DATABASE_URL explícitamente.
    raise RuntimeError(
        "DATABASE_URL no está configurada. "
        "Configura la URL de conexión directa a Postgres. "
        "Formato: postgresql+asyncpg://user:pass@host:port/dbname"
    )


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            _get_database_url(),
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager para obtener una session de DB."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_engine() -> None:
    """Cerrar el engine al apagar el proceso."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
