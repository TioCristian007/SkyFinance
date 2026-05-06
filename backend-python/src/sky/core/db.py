"""
sky.core.db — SQLAlchemy async engine + session factory.

Usa las mismas tablas de Supabase. Cero migración de datos.
El engine se crea una vez al inicio del proceso y se reutiliza.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from supabase import Client, create_client

# En producción esto viene de una variable DATABASE_URL directa.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_database_url() -> str:
    """
    Construye la URL de conexión.
    En producción: usar DATABASE_URL directa (más limpio).
    """
    import os
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    raise RuntimeError(
        "DATABASE_URL no está configurada. "
        "Formato: postgresql+asyncpg://user:pass@host:port/dbname"
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            _get_database_url(),
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    assert _session_factory is not None
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


# ── Supabase ARIA client ───────────────────────────────────────────────────────

_aria_client: Client | None = None


def get_aria_client() -> Client:
    """
    Retorna un cliente Supabase con service_role para escribir en schema aria.*.

    Cliente separado del engine SQLAlchemy. Usa SUPABASE_SERVICE_KEY, nunca
    la anon key. Callers usan: get_aria_client().schema("aria").table(...).
    """
    global _aria_client
    if _aria_client is None:
        from sky.core.config import settings

        _aria_client = create_client(
            settings.supabase_url,
            settings.supabase_service_key,
        )
    return _aria_client
