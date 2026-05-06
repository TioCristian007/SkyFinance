"""
sky.worker.main — Entry point del worker ARQ.

Este proceso NUNCA sirve HTTP. Solo ejecuta jobs de las colas.
El browser pool se inicia aquí y se comparte entre jobs.

Arranque:
    arq sky.worker.main.WorkerSettings
"""
from __future__ import annotations

from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from arq.cron import cron

from sky.core.config import settings
from sky.core.logging import get_logger, setup_logging
from sky.ingestion.bootstrap import build_router
from sky.ingestion.browser_pool import get_browser_pool
from sky.worker.jobs.categorize import categorize_pending_job
from sky.worker.jobs.scheduled import scheduled_sync_job
from sky.worker.jobs.sync import sync_all_user_accounts_job, sync_bank_account_job

logger = get_logger("worker")


async def startup(ctx: dict[str, Any]) -> None:
    """Inicializar recursos compartidos del worker."""
    setup_logging(json_output=settings.is_production)
    logger.info("worker_starting")

    pool = get_browser_pool()
    await pool.start()
    ctx["browser_pool"] = pool

    router, redis = await build_router(include_browser_sources=True)
    ctx["router"] = router
    ctx["redis"] = redis

    # Pool de ARQ para encolar jobs desde dentro de otros jobs
    ctx["arq_pool"] = await create_pool(RedisSettings.from_dsn(settings.redis_url))

    logger.info("worker_ready", pool_size=settings.browser_pool_size)


async def shutdown(ctx: dict[str, Any]) -> None:
    """Liberar recursos al apagar."""
    pool = ctx.get("browser_pool")
    if pool:
        await pool.stop()
    arq_pool = ctx.get("arq_pool")
    if arq_pool:
        await arq_pool.aclose()
    redis = ctx.get("redis")
    if redis:
        await redis.aclose()
    logger.info("worker_stopped")


class WorkerSettings:
    """Configuración del worker ARQ."""

    redis_settings = RedisSettings.from_dsn(settings.redis_url)

    on_startup = startup
    on_shutdown = shutdown

    functions = [
        sync_bank_account_job,
        sync_all_user_accounts_job,
        categorize_pending_job,
        scheduled_sync_job,
    ]

    cron_jobs = [
        cron(scheduled_sync_job, minute=5),  # cada hora a los :05 min
    ]

    queue_name = "sky:default"
    max_jobs = settings.browser_pool_size * 2
    job_timeout = 600   # 10 min max por job (syncs pueden tardar)
    keep_result = 3600  # resultados en Redis por 1h
