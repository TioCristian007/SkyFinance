"""
sky.worker.jobs.scheduled — Cron ARQ: scheduler de auto-sync.

Replica runScheduledSync() de Node (backend/services/schedulerService.js).

Corre cada hora a los :05 minutos vía arq.cron. En cada tick:
  1. Obtiene cuentas candidatas (status active/error, auto_sync_enabled=true).
  2. Filtra por backoff exponencial en Python (idéntico a Node).
  3. Encola sync_bank_account_job por cada cuenta elegible.

El advisory lock en banking_sync.py garantiza que si un sync manual
y el cron se pisan sobre la misma cuenta, uno cede sin error.

Pre-requisito de deploy: migration 003 (profiles.auto_sync_enabled).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("scheduler")


async def scheduled_sync_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Cron ARQ: encola sync de cuentas elegibles con backoff exponencial.

    Backoff (idéntico a Node, schedulerService.js:88-101):
      interval = min(base_hours * factor^errors, max_hours)
      Con defaults: min(1 * 2^errors, 24) horas.
      - 0 errors: 1h  · 1 error: 2h  · 2 errors: 4h
      - 3 errors: 8h  · 4 errors: 16h · 5+ errors: 24h (cap)
      Cuentas con consecutive_errors >= max_consecutive_errors excluidas en SQL.
    """
    started_at = datetime.now(UTC)
    logger.info("scheduler_tick_start")

    # 1. Candidatos: status activo/error + auto_sync_enabled + bajo umbral de errores.
    #    JOIN profiles idéntico al de Node (schedulerService.js:68-76).
    #    Requiere migration 003 (profiles.auto_sync_enabled).
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT ba.id, ba.user_id, ba.consecutive_errors, ba.last_scheduled_at
                  FROM public.bank_accounts ba
                  JOIN public.profiles p ON p.id = ba.user_id
                 WHERE ba.status IN ('active', 'error')
                   AND p.auto_sync_enabled = true
                   AND COALESCE(ba.consecutive_errors, 0) < :max_errors
                 ORDER BY ba.last_scheduled_at ASC NULLS FIRST
                 LIMIT :limit
            """),
            {
                "max_errors": settings.scheduler_max_consecutive_errors,
                "limit": settings.scheduler_max_per_tick * 3,
            },
        )
        candidates = list(rs.mappings().all())

    if not candidates:
        logger.info("scheduler_no_candidates")
        return {"processed": 0}

    # 2. Filtro de backoff exponencial en Python — replica Node schedulerService.js:88-101.
    #    Fórmula: min(base_hours * factor^errors, max_hours).
    #    Cuando last_scheduled_at=None → siempre due (Node: lastScheduledMs=0).
    now = datetime.now(UTC)
    due = []
    for acc in candidates:
        errors = int(acc["consecutive_errors"] or 0)
        interval_hours = min(
            settings.scheduler_base_interval_hours
            * (settings.scheduler_backoff_factor**errors),
            settings.scheduler_max_backoff_hours,
        )
        last = acc["last_scheduled_at"]
        if last is None:
            due.append(acc)
        else:
            # asyncpg puede devolver datetime naive o aware según configuración del driver.
            last_aware = last if last.tzinfo else last.replace(tzinfo=UTC)
            elapsed_hours = (now - last_aware).total_seconds() / 3600
            if elapsed_hours >= interval_hours:
                due.append(acc)

    to_process = due[: settings.scheduler_max_per_tick]
    logger.info(
        "scheduler_candidates",
        candidates=len(candidates),
        due=len(due),
        to_process=len(to_process),
    )

    if not to_process:
        return {"processed": 0, "skipped": len(candidates)}

    # 3. Encolar sync por cuenta. Advisory lock en banking_sync evita race
    #    si el mismo bank_account_id ya tiene un sync manual en curso.
    arq_pool = ctx["arq_pool"]
    ok, fail = 0, 0
    for acc in to_process:
        job = await arq_pool.enqueue_job(
            "sync_bank_account_job",
            str(acc["id"]),
            str(acc["user_id"]),
        )
        if job:
            ok += 1
        else:
            fail += 1

    elapsed_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
    logger.info("scheduler_tick_done", ok=ok, fail=fail, elapsed_ms=elapsed_ms)
    return {"processed": ok + fail, "ok": ok, "fail": fail, "elapsed_ms": elapsed_ms}
