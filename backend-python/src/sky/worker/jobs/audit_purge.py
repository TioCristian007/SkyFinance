"""sky.worker.jobs.audit_purge — Purge diario del audit log (retención configurable).

max_tries=1: ARQ no auto-retry. Si falla, el operador puede encolar manualmente
o esperar el siguiente tick del cron (siguiente día a las 03:00 UTC). Un fallo
de purge no es crítico — solo retrasa la limpieza, no bloquea el hot path.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("audit_purge")


async def audit_purge_job(ctx: dict[str, Any]) -> dict[str, int]:
    """
    Elimina registros de public.audit_log vencidos según audit_log_retention_days.

    Cron ARQ: daily 03:00 UTC (pg_cron no instalado en este Supabase).
    Batchea en grupos de 10 000 (max 50 iter) — evita lock prolongado.
    NO llama a log_event() — el purge no se auto-audita (recursión filosófica).
    max_tries=1 — ARQ no reintentar en fallo.
    """
    days = settings.audit_log_retention_days
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT public.purge_audit_log_old(:days)"),
            {"days": days},
        )
        deleted = result.scalar() or 0
    logger.info("audit_purge_completed", deleted=deleted, retention_days=days)
    return {"deleted": deleted}


audit_purge_job.max_tries = 1  # type: ignore[attr-defined]
