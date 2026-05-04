"""
sky.worker.jobs.sync — ARQ jobs de sincronización bancaria.

Funciones registradas:
    - sync_bank_account_job(bank_account_id, user_id): sync de UNA cuenta.
    - sync_all_user_accounts_job(user_id): encola N jobs (uno por cuenta activa).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.worker.banking_sync import sync_bank_account

logger = get_logger("jobs.sync")


async def sync_bank_account_job(
    ctx: dict[str, Any],
    bank_account_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Job ARQ: sincroniza UNA cuenta bancaria."""
    router = ctx["router"]
    arq_pool = ctx["arq_pool"]
    result: dict[str, Any] = await sync_bank_account(
        router=router,
        bank_account_id=bank_account_id,
        user_id=user_id,
        arq_pool=arq_pool,
    )
    return result


async def sync_all_user_accounts_job(
    ctx: dict[str, Any],
    user_id: str,
) -> dict[str, Any]:
    """
    Job ARQ: encola un job de sync por cada cuenta activa del user.
    NO sincroniza secuencialmente — cada cuenta corre como job propio,
    permitiendo paralelismo limitado por el browser pool del worker.
    Cierra BUG-4 (sync secuencial entre bancos del mismo user).
    """
    arq_pool = ctx["arq_pool"]
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id FROM public.bank_accounts
                 WHERE user_id = :uid AND status != 'disconnected'
            """),
            {"uid": user_id},
        )
        ids = [str(row[0]) for row in rs.fetchall()]

    enqueued = 0
    for account_id in ids:
        await arq_pool.enqueue_job("sync_bank_account_job", account_id, user_id)
        enqueued += 1

    logger.info("sync_all_enqueued", user_id=user_id, count=enqueued)
    return {"enqueued": enqueued}
