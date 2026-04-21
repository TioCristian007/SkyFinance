"""
sky.worker.main — Entry point del worker ARQ.

Este proceso NUNCA sirve HTTP. Solo ejecuta jobs de las colas.
El browser pool se inicia aquí y se comparte entre jobs.

Arranque:
    arq sky.worker.main.WorkerSettings
"""

from arq import cron
from arq.connections import RedisSettings

from sky.core.config import settings
from sky.core.logging import setup_logging, get_logger
from sky.ingestion.browser_pool import get_browser_pool

logger = get_logger("worker")


async def startup(ctx: dict) -> None:
    """Inicializar recursos compartidos del worker."""
    setup_logging(json_output=settings.is_production)
    logger.info("worker_starting")

    # Iniciar browser pool (Playwright)
    pool = get_browser_pool()
    await pool.start()
    ctx["browser_pool"] = pool

    logger.info("worker_ready", pool_size=settings.browser_pool_size)


async def shutdown(ctx: dict) -> None:
    """Liberar recursos al apagar."""
    pool = ctx.get("browser_pool")
    if pool:
        await pool.stop()
    logger.info("worker_stopped")


class WorkerSettings:
    """Configuración del worker ARQ."""

    redis_settings = RedisSettings.from_dsn(settings.redis_url)

    on_startup = startup
    on_shutdown = shutdown

    # Funciones de jobs — se importan al implementar cada fase
    functions: list = [
        # TODO (Fase 6): importar jobs
        # sync_bank_account_job,
        # categorize_pending_job,
    ]

    # Cron jobs
    cron_jobs = [
        # TODO (Fase 9): scheduler como cron ARQ
        # cron(scheduled_sync_job, hour=None, minute={0}),  # cada hora
    ]

    # Configuración
    max_jobs = 10
    job_timeout = 600  # 10 min max por job (syncs pueden tardar)
    keep_result = 3600  # resultados en Redis por 1h
