"""
scripts/enqueue_categorize.py — Encola categorize_pending_job una vez.

Útil para patear el drenado de un backlog de transacciones que quedaron en
categorization_status='pending' sin ser procesadas (ej. tras un backfill grande).
El job se re-encola automáticamente en cascada hasta vaciar la cola.

Uso:
    python scripts/enqueue_categorize.py

Requiere que el worker ARQ esté corriendo para que el job se ejecute.
"""
from __future__ import annotations

import asyncio

from arq import create_pool
from arq.connections import RedisSettings

from sky.core.config import settings
from sky.core.logging import get_logger, setup_logging

setup_logging(json_output=False)
logger = get_logger("enqueue_categorize")


async def main() -> None:
    pool = await create_pool(
        RedisSettings.from_dsn(settings.redis_url),
        default_queue_name="sky:default",
    )
    try:
        job = await pool.enqueue_job("categorize_pending_job")
        if job:
            logger.info("enqueued", job_id=job.job_id)
        else:
            logger.warning(
                "enqueue_returned_none",
                hint="El job puede ya estar en cola o ARQ rechazó el encolado",
            )
    finally:
        await pool.aclose()


if __name__ == "__main__":
    asyncio.run(main())
