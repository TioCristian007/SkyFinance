"""sky.api.routers.internal — Endpoints internos (cron, admin)."""
from __future__ import annotations

import contextlib
import json
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("api.internal")
router = APIRouter(prefix="/api/internal", tags=["internal"])


def _require_cron_secret(request: Request) -> None:
    """Auth de operador via x-cron-secret. Secret vacío = endpoint cerrado."""
    secret = request.headers.get("x-cron-secret", "")
    if not secret or not settings.cron_secret or not secrets.compare_digest(
        secret, settings.cron_secret
    ):
        raise HTTPException(status_code=401, detail="Cron secret inválido")


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
    logger.warning(
        "cron_sync_due_deprecated",
        reason="Replaced by ARQ cron (scheduled_sync_job). Will be removed in Fase 13.",
    )

    _require_cron_secret(request)

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
                   AND status NOT IN ('disconnected', 'waiting_2fa', 'needs_reconnection')
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


@router.get("/operator/sync-status")
async def operator_sync_status(request: Request) -> dict[str, Any]:
    """C2 (sprint 2026-06-12): panel mínimo de operador.

    Estado + último error real de cada cuenta bancaria sin scripts ad-hoc
    ni acceso directo a la DB. Autenticado con x-cron-secret (operador,
    nunca usuarios). Sin PII: no expone user_id, RUT ni credenciales —
    last_sync_error ya es el mensaje sanitizado y el detail del audit_log
    lleva failure_kind + str(exc) truncado (las excepciones de ingesta
    jamás contienen credenciales).
    """
    _require_cron_secret(request)

    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id, bank_id, status, consecutive_errors, sync_count,
                       last_sync_at, last_sync_error, updated_at
                  FROM public.bank_accounts
                 ORDER BY updated_at DESC
                 LIMIT 100
            """)
        )
        accounts = [dict(r) for r in rs.mappings().all()]

        # Último evento bank_sync por cuenta (success o failure) — el detail
        # jsonb trae failure_kind/cause_type del worker.
        rs2 = await conn.execute(
            text("""
                SELECT DISTINCT ON (resource_id)
                       resource_id, outcome, detail, occurred_at
                  FROM public.audit_log
                 WHERE event_type = 'bank_sync' AND resource_id IS NOT NULL
                 ORDER BY resource_id, occurred_at DESC
            """)
        )
        last_events = {str(r["resource_id"]): dict(r) for r in rs2.mappings().all()}

    out: list[dict[str, Any]] = []
    for acc in accounts:
        acc_id = str(acc["id"])
        ev = last_events.get(acc_id)
        ev_out: dict[str, Any] | None = None
        if ev:
            detail = ev["detail"]
            if isinstance(detail, str):
                # asyncpg puede devolver jsonb como str; dejar crudo si no parsea
                with contextlib.suppress(ValueError):
                    detail = json.loads(detail)
            ev_out = {
                "outcome": ev["outcome"],
                "detail": detail,
                "occurred_at": ev["occurred_at"].isoformat() if ev["occurred_at"] else None,
            }
        out.append({
            "id": acc_id,
            "bank_id": str(acc["bank_id"]),
            "status": str(acc["status"] or ""),
            "consecutive_errors": int(acc["consecutive_errors"] or 0),
            "sync_count": int(acc["sync_count"] or 0),
            "last_sync_at": acc["last_sync_at"].isoformat() if acc["last_sync_at"] else None,
            "last_sync_error": acc["last_sync_error"],
            "last_sync_event": ev_out,
        })

    return {"accounts": out, "count": len(out)}
