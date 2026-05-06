"""sky.api.routers.internal — Endpoints internos (cron, admin)."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("api.internal")
router = APIRouter(prefix="/api/internal", tags=["internal"])


@router.post("/cron/sync-due")
async def cron_sync_due(request: Request) -> dict[str, int]:
    """
    [DEPRECATED — Fase 9] Endpoint externo de cron. Reemplazado por el cron
    nativo ARQ (scheduled_sync_job en worker/jobs/scheduled.py).
    Se mantiene por compatibilidad mientras se valida el cron ARQ en producción.
    Eliminar en Fase 11 durante cleanup pre-deploy.

    Encola sync de cuentas cuyo last_sync_at supera el umbral de horas.
    Autenticado via x-cron-secret (Railway cron / GitHub Actions).
    """
    secret = request.headers.get("x-cron-secret", "")
    if not secret or not secrets.compare_digest(secret, settings.cron_secret):
        raise HTTPException(status_code=401, detail="Cron secret inválido")

    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id, user_id
                  FROM public.bank_accounts
                 WHERE (
                   last_sync_at IS NULL
                   OR last_sync_at < NOW() - (:hours * INTERVAL '1 hour')
                 )
                   AND consecutive_errors < :max_errors
                   AND status NOT IN ('disconnected', 'waiting_2fa')
                 ORDER BY last_sync_at ASC NULLS FIRST
                 LIMIT 100
            """),
            {
                "hours": settings.scheduler_due_threshold_hours,
                "max_errors": settings.scheduler_max_consecutive_errors,
            },
        )
        accounts = rs.fetchall()

    arq_pool = request.app.state.arq_pool
    enqueued = 0
    for row in accounts:
        job = await arq_pool.enqueue_job(
            "sync_bank_account_job", str(row[0]), str(row[1]),
        )
        if job:
            enqueued += 1

    logger.info("cron_sync_due", enqueued=enqueued, total_due=len(accounts))
    return {"enqueued": enqueued}
