"""
sky.core.locks — Advisory locks distribuidos vía Postgres.

Reemplaza los Set() en memoria de Node que no escalan con múltiples workers.
Usa pg_try_advisory_lock con key derivada del hash del bank_account_id.

Uso:
    async with advisory_lock(session, f"sync:{bank_account_id}") as acquired:
        if not acquired:
            return  # otro worker ya lo tiene
        await do_sync(...)
"""

import hashlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _key_to_int64(key: str) -> int:
    """Convierte un string arbitrario a un int64 para pg_advisory_lock."""
    h = hashlib.sha256(key.encode("utf-8")).digest()
    # Tomar los primeros 8 bytes como signed int64
    return int.from_bytes(h[:8], byteorder="big", signed=True)


@asynccontextmanager
async def advisory_lock(
    session: AsyncSession,
    key: str,
) -> AsyncGenerator[bool, None]:
    """
    Intenta adquirir un advisory lock no-bloqueante.

    Yields:
        True si se adquirió el lock, False si otro worker lo tiene.

    El lock se libera automáticamente al salir del context manager.
    """
    lock_id = _key_to_int64(key)
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:id)"),
        {"id": lock_id},
    )
    acquired = result.scalar()

    try:
        yield bool(acquired)
    finally:
        if acquired:
            await session.execute(
                text("SELECT pg_advisory_unlock(:id)"),
                {"id": lock_id},
            )
