"""sky.core.locks — Postgres advisory locks distribuidos.

Reemplaza los Set() en memoria de Node que no escalan con múltiples workers.
Usa pg_try_advisory_lock con key derivada de SHA-256 del string proporcionado.

Uso:
    async with try_advisory_lock(f"sync:{bank_account_id}") as got:
        if not got:
            return  # otro worker ya lo tiene
        await do_sync(...)
"""
from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text

from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("locks")


def _key_from_string(s: str) -> int:
    """SHA-256 → int64 estable. Postgres pg_try_advisory_lock acepta bigint."""
    h = hashlib.sha256(s.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big", signed=True)


@asynccontextmanager
async def try_advisory_lock(key_str: str) -> AsyncIterator[bool]:
    """
    Adquiere un advisory lock no-bloqueante vía pg_try_advisory_lock.

    Yields True si se adquirió el lock, False si ya estaba tomado.
    El lock se libera automáticamente al salir del bloque.
    """
    key = _key_from_string(key_str)
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
        )
        got = bool(result.scalar())
        try:
            yield got
        finally:
            if got:
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": key}
                )
                await conn.commit()
