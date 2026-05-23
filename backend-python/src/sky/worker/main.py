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
from sky.core.sentry_utils import init_sentry
from sky.ingestion.bootstrap import build_router
from sky.ingestion.browser_pool import get_browser_pool
from sky.worker.jobs.audit_purge import audit_purge_job
from sky.worker.jobs.categorize import categorize_pending_job
from sky.worker.jobs.data_export import process_export_request_job
from sky.worker.jobs.scheduled import scheduled_sync_job
from sky.worker.jobs.sync import sync_all_user_accounts_job, sync_bank_account_job

logger = get_logger("worker")


async def startup(ctx: dict[str, Any]) -> None:
    """Inicializar recursos compartidos del worker."""
    init_sentry()
    setup_logging(json_output=settings.is_production)
    logger.info("worker_starting")

    pool = get_browser_pool()
    await pool.start()
    ctx["browser_pool"] = pool

    router, redis = await build_router(include_browser_sources=True)
    ctx["router"] = router
    ctx["redis"] = redis

    # Pool de ARQ para encolar jobs desde dentro de otros jobs
    ctx["arq_pool"] = await create_pool(
        RedisSettings.from_dsn(settings.redis_url),
        default_queue_name="sky:default",
    )

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
        audit_purge_job,                     # Fase 12: daily 03:00 UTC
        process_export_request_job,          # Fase 12: data export Ley 19.628
    ]

    cron_jobs = [
        cron(scheduled_sync_job, minute=5),              # cada hora a los :05
        cron(audit_purge_job, hour=3, minute=0),         # daily 03:00 UTC
    ]

    queue_name = "sky:default"
    max_jobs = settings.browser_pool_size * 2
    job_timeout = 600   # 10 min max por job (syncs pueden tardar)
    keep_result = 3600  # resultados en Redis por 1h
    # Errores terminales (BankAuthError, AllSourcesFailedError) retornan dict de fallo
    # sin re-lanzar, por lo que ARQ no los reintenta. max_tries=2 protege solo ante
    # errores inesperados (DB blip, etc.) — un scrape con 2FA como máximo se repite 1 vez.
    max_tries = 2
