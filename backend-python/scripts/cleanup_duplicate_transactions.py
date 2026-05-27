"""
scripts/cleanup_duplicate_transactions.py

Purga transacciones duplicadas históricas y re-sincroniza limpio.

CONTEXTO
--------
La Tanda 1 corrigió build_external_id para usar el id nativo del banco
(`{bank_id}:native:{native_id}`). Las transacciones creadas con la fórmula
anterior pueden haber generado duplicados. Este script (Tanda 2) las purga
y dispara un sync limpio para reconstruir el historial con la lógica vigente.

MODOS
-----
1) DRY-RUN (default, sin --apply):
   Cuenta y reporta. No borra nada.
   - Total de transacciones por bank_account (todas, incluyendo soft-deleted).
   - Transacciones del mes en curso.
   - Transacciones con bank_account_id IS NULL (manuales — INTOCABLES).
   - Cuántas se borrarían.

2) APPLY (--apply + confirmación interactiva):
   Hard DELETE de las transacciones del scraper (bank_account_id IS NOT NULL).
   PRESERVA las manuales (bank_account_id IS NULL).
   Resetea last_sync_at = NULL para forzar backfill de 90 días.
   Encola sync_bank_account_job vía ARQ (mismo mecanismo que el botón Actualizar).

USO
---
    # DRY-RUN (seguro):
    python scripts/cleanup_duplicate_transactions.py
    python scripts/cleanup_duplicate_transactions.py --user-id <UUID>
    python scripts/cleanup_duplicate_transactions.py --bank-account-id <UUID>

    # EJECUTAR (destructivo — requiere confirmación):
    python scripts/cleanup_duplicate_transactions.py --apply --bank-account-id <UUID>

ENV REQUERIDAS (.env o entorno)
--------------------------------
    DATABASE_URL, SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY,
    ANTHROPIC_API_KEY, BANK_ENCRYPTION_KEY
    REDIS_URL (default: redis://localhost:6379)

VERIFICACIÓN POST-APPLY
-----------------------
    1. Conteo del mes: ANTES > 0, DESPUÉS = 0.
    2. Primer sync → new_transactions > 0 (reconstruye el historial).
    3. Segundo sync seguido → new_transactions = 0 (dedup por id nativo es estable).
    4. Total post-limpieza debe cuadrar con los movimientos reales del banco.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import close_engine, get_engine
from sky.core.logging import get_logger, setup_logging

setup_logging(json_output=False)  # consola legible para uso interactivo
logger = get_logger("cleanup_duplicates")

_TODAY = date.today()
_MONTH_START = _TODAY.replace(day=1)


# ── Queries de DB ─────────────────────────────────────────────────────────────

async def _fetch_accounts(
    user_id: str | None,
    bank_account_id: str | None,
) -> list[dict]:
    """
    Retorna bank_accounts activas (status != 'disconnected') que coinciden
    con los filtros. Sin filtros devuelve TODAS las cuentas del sistema
    (útil en alpha con un solo usuario).
    """
    engine = get_engine()
    where_parts = ["status != 'disconnected'"]
    params: dict[str, object] = {}
    if user_id:
        where_parts.append("user_id = :uid")
        params["uid"] = user_id
    if bank_account_id:
        where_parts.append("id = :bid")
        params["bid"] = bank_account_id
    where_sql = " AND ".join(where_parts)

    async with engine.connect() as conn:
        rs = await conn.execute(
            text(
                "SELECT id, user_id, bank_id, bank_name, status, sync_count, last_sync_at"
                " FROM public.bank_accounts"
                f" WHERE {where_sql}"
                " ORDER BY created_at ASC"
            ),
            params,
        )
        return [dict(r._mapping) for r in rs.fetchall()]


async def _count_tx(user_id: str, bank_account_id: str) -> dict[str, int]:
    """
    Cuenta transacciones para un bank_account dado.
    Incluye soft-deleted (deleted_at IS NOT NULL) en el total_all.
    """
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT
                    COUNT(*)                                           AS total_all,
                    COUNT(*) FILTER (WHERE deleted_at IS NULL)         AS total_active,
                    COUNT(*) FILTER (WHERE deleted_at IS NULL
                                      AND date >= :ms)                AS this_month
                  FROM public.transactions
                 WHERE user_id = :uid AND bank_account_id = :bid
            """),
            {"uid": user_id, "bid": bank_account_id, "ms": _MONTH_START},
        )
        row = rs.mappings().first()

        # Manuales (bank_account_id IS NULL) — NUNCA se tocan
        rs2 = await conn.execute(
            text("""
                SELECT COUNT(*) AS manual
                  FROM public.transactions
                 WHERE user_id = :uid AND bank_account_id IS NULL AND deleted_at IS NULL
            """),
            {"uid": user_id},
        )
        manual_row = rs2.mappings().first()

    return {
        "total_all": int(row["total_all"] or 0),
        "total_active": int(row["total_active"] or 0),
        "this_month": int(row["this_month"] or 0),
        "manual": int(manual_row["manual"] or 0),
    }


async def _hard_delete_account_tx(user_id: str, bank_account_id: str) -> int:
    """
    Hard DELETE de TODAS las transacciones de un bank_account (activas + soft-deleted).
    Las manuales (bank_account_id IS NULL) no se tocan — el WHERE las excluye implícitamente.
    Devuelve filas borradas.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("""
                DELETE FROM public.transactions
                 WHERE user_id = :uid AND bank_account_id = :bid
            """),
            {"uid": user_id, "bid": bank_account_id},
        )
        return int(rs.rowcount or 0)


async def _reset_sync_state(bank_account_id: str) -> None:
    """
    Resetea last_sync_at = NULL para que el siguiente sync haga backfill de 90 días
    (no incremental). Sin esto, el worker solo traería los últimos 3 días.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE public.bank_accounts
                   SET last_sync_at = NULL,
                       updated_at   = NOW()
                 WHERE id = :bid
            """),
            {"bid": bank_account_id},
        )


async def _enqueue_sync(user_id: str, bank_account_id: str) -> str | None:
    """
    Encola sync_bank_account_job vía ARQ (mismo mecanismo que POST /api/banking/sync/{id}).
    Devuelve el job_id encolado, o None si ARQ no pudo crearlo.
    """
    pool = await create_pool(
        RedisSettings.from_dsn(settings.redis_url),
        default_queue_name="sky:default",
    )
    try:
        job = await pool.enqueue_job("sync_bank_account_job", bank_account_id, user_id)
        return job.job_id if job else None
    finally:
        await pool.aclose()


# ── Modo DRY-RUN ──────────────────────────────────────────────────────────────

async def dry_run(user_id: str | None, bank_account_id: str | None) -> None:
    logger.info(
        "dry_run_start",
        mes_referencia=_MONTH_START.isoformat(),
        filtro_user_id=user_id or "todos",
        filtro_bank_account_id=bank_account_id or "todos",
    )

    accounts = await _fetch_accounts(user_id, bank_account_id)
    if not accounts:
        logger.warning(
            "no_accounts_found",
            user_id=user_id,
            bank_account_id=bank_account_id,
            hint="Verificá los UUIDs o que la cuenta no esté en status=disconnected",
        )
        return

    grand_total_all = 0
    grand_this_month = 0
    grand_would_delete = 0

    for acc in accounts:
        uid = str(acc["user_id"])
        bid = str(acc["id"])
        counts = await _count_tx(uid, bid)

        grand_total_all += counts["total_all"]
        grand_this_month += counts["this_month"]
        grand_would_delete += counts["total_all"]

        logger.info(
            "account_dry_run",
            bank_account_id=bid,
            bank_id=acc["bank_id"],
            bank_name=acc["bank_name"],
            user_id=uid,
            status=acc["status"],
            last_sync_at=str(acc["last_sync_at"]) if acc["last_sync_at"] else None,
            # ── conteos ───────────────────────────────────────────────
            total_all_rows=counts["total_all"],
            total_active=counts["total_active"],
            this_month_active=counts["this_month"],
            manual_intocables=counts["manual"],
            would_delete=counts["total_all"],
        )

    logger.info(
        "dry_run_summary",
        accounts_analizadas=len(accounts),
        total_filas_en_db=grand_total_all,
        filas_este_mes=grand_this_month,
        filas_que_se_borrarian=grand_would_delete,
        manuales_preservadas="todas (bank_account_id IS NULL nunca se toca)",
        accion="DRY-RUN — no se borró nada",
        siguiente_paso="Correr con --apply [--bank-account-id UUID] para ejecutar",
    )


# ── Modo APPLY ────────────────────────────────────────────────────────────────

async def apply_cleanup(user_id: str | None, bank_account_id: str | None) -> None:
    accounts = await _fetch_accounts(user_id, bank_account_id)
    if not accounts:
        logger.warning(
            "no_accounts_found",
            user_id=user_id,
            bank_account_id=bank_account_id,
        )
        return

    # ── Confirmación interactiva ──────────────────────────────────────────────
    print()
    print("=" * 70)
    print("⚠️  APPLY — OPERACIÓN DESTRUCTIVA (hard DELETE + re-sync)")
    print("=" * 70)
    print()
    print(f"  Se borrarán TODAS las transacciones de {len(accounts)} cuenta(s):")
    for acc in accounts:
        print(
            f"    • {acc['bank_name']} ({acc['bank_id']})"
            f"  account_id={acc['id']}"
            f"  user_id={acc['user_id']}"
        )
    print()
    print("  Las manuales (bank_account_id IS NULL) NO se tocan.")
    print("  Se reseteará last_sync_at para forzar backfill de 90 días.")
    print("  Se encolará sync_bank_account_job en ARQ.")
    print()

    confirm = input("  Escribí CONFIRMAR para continuar (Ctrl+C para cancelar): ").strip()
    if confirm != "CONFIRMAR":
        logger.info("apply_aborted", razon="confirmacion_no_recibida")
        print("\nAbortado.")
        return

    print()
    logger.info("apply_start", accounts_count=len(accounts))

    total_deleted = 0

    for acc in accounts:
        uid = str(acc["user_id"])
        bid = str(acc["id"])
        bank = acc["bank_id"]

        # Conteo ANTES
        before = await _count_tx(uid, bid)
        logger.info(
            "before_delete",
            bank_account_id=bid,
            bank_id=bank,
            total_all=before["total_all"],
            total_active=before["total_active"],
            this_month=before["this_month"],
            manual_intocables=before["manual"],
        )

        # Hard DELETE (solo bank_account_id IS NOT NULL — las manuales quedan)
        deleted = await _hard_delete_account_tx(uid, bid)
        total_deleted += deleted
        logger.info("deleted", bank_account_id=bid, bank_id=bank, rows_deleted=deleted)

        # Conteo DESPUÉS del delete
        after = await _count_tx(uid, bid)
        logger.info(
            "after_delete",
            bank_account_id=bid,
            bank_id=bank,
            total_all=after["total_all"],
            total_active=after["total_active"],
            this_month=after["this_month"],
            manual_preservadas=after["manual"],
        )

        # Reset last_sync_at → backfill de 90 días en el próximo sync
        await _reset_sync_state(bid)
        logger.info("sync_state_reset", bank_account_id=bid, last_sync_at="NULL → 90d backfill")

        # Encolar sync limpio
        job_id = await _enqueue_sync(uid, bid)
        if job_id:
            logger.info(
                "sync_enqueued",
                bank_account_id=bid,
                bank_id=bank,
                job_id=job_id,
                nota="El worker procesará el job; revisá sus logs para new_transactions",
            )
        else:
            logger.warning(
                "sync_enqueue_failed",
                bank_account_id=bid,
                bank_id=bank,
                hint="ARQ retornó None — revisá Redis y volvé a encolar manualmente",
            )

    logger.info(
        "apply_done",
        accounts_procesadas=len(accounts),
        total_filas_borradas=total_deleted,
        verificacion_1="Revisá logs del worker: new_transactions > 0 en el primer sync",
        verificacion_2="Segundo sync seguido debe dar new_transactions = 0",
        verificacion_3="Total post-limpieza debe cuadrar con movimientos reales del banco",
    )


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Purga transacciones duplicadas históricas y re-sincroniza limpio. "
            "Sin --apply corre en DRY-RUN (solo reporta, no borra)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Ejecutar el borrado real (requiere confirmación interactiva).",
    )
    parser.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        metavar="UUID",
        help="Filtrar por user_id. Sin este flag procesa TODOS los usuarios (alpha: uno solo).",
    )
    parser.add_argument(
        "--bank-account-id",
        dest="bank_account_id",
        default=None,
        metavar="UUID",
        help="Filtrar por bank_account_id específico. Recomendado para acotar el impacto.",
    )
    args = parser.parse_args()

    try:
        if args.apply:
            await apply_cleanup(args.user_id, args.bank_account_id)
        else:
            await dry_run(args.user_id, args.bank_account_id)
    finally:
        await close_engine()


if __name__ == "__main__":
    asyncio.run(main())
