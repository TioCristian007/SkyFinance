"""
sky.worker.banking_sync — Orquestador de sync por cuenta bancaria.

Llamado por el job `sync_bank_account_job`. Toma:
    - bank_account_id (uuid)
    - user_id (uuid)
Usa:
    - `IngestionRouter` (ya construido en `ctx["router"]`)
    - `pg_try_advisory_lock` para evitar syncs duplicados (cierra BUG-3)
    - `INSERT ... ON CONFLICT (user_id, bank_account_id, external_id) DO NOTHING`
      para idempotencia (cierra BUG-1, BUG-2)

Devuelve dict con:
    - success: bool
    - new_transactions: int
    - balance: int (CLP) | None
    - bank_id: str
    - elapsed_ms: int
    - skipped: bool (True si advisory lock estaba tomado)

NUNCA logea credenciales ni descripción fuera del scope necesario.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.encryption import decrypt
from sky.core.errors import NotFoundError
from sky.core.locks import try_advisory_lock
from sky.core.logging import get_logger
from sky.ingestion.contracts import AllSourcesFailedError, BankCredentials
from sky.ingestion.contracts import AuthenticationError as BankAuthError
from sky.ingestion.routing.router import IngestionRouter

logger = get_logger("banking_sync")


async def sync_bank_account(
    *,
    router: IngestionRouter,
    bank_account_id: str,
    user_id: str,
    arq_pool: Any,  # ArqRedis — para encolar categorize_pending_job al final
) -> dict[str, Any]:
    """Sincroniza UNA cuenta bancaria. Idempotente. Lock por bank_account_id."""
    started_at = datetime.now(UTC)

    async with try_advisory_lock(f"sync:bank_account:{bank_account_id}") as got:
        if not got:
            logger.info("sync_skipped_locked", bank_account_id=bank_account_id)
            return {"skipped": True, "reason": "lock_held"}

        engine = get_engine()
        async with engine.begin() as conn:
            row = (await conn.execute(
                text("""
                    SELECT id, user_id, bank_id, encrypted_rut, encrypted_pass,
                           sync_count, consecutive_errors
                      FROM public.bank_accounts
                     WHERE id = :id AND user_id = :uid AND status != 'disconnected'
                """),
                {"id": bank_account_id, "uid": user_id},
            )).mappings().first()
            if row is None:
                raise NotFoundError(f"bank_account not found: {bank_account_id}")

            await conn.execute(
                text("""
                    UPDATE public.bank_accounts
                       SET status = 'active',
                           last_sync_error = NULL,
                           last_scheduled_at = NOW(),
                           updated_at = NOW()
                     WHERE id = :id
                """),
                {"id": bank_account_id},
            )

        # Descifrar credenciales SOLO en memoria.
        rut = decrypt(str(row["encrypted_rut"]), settings.bank_encryption_key)
        password = decrypt(str(row["encrypted_pass"]), settings.bank_encryption_key)
        creds = BankCredentials(rut=rut, password=password)
        bank_id = str(row["bank_id"])

        try:
            result = await router.ingest(bank_id=bank_id, user_id=user_id, credentials=creds)
        except BankAuthError:
            await _mark_error(bank_account_id, "Credenciales rechazadas por el banco")
            raise
        except AllSourcesFailedError as exc:
            await _mark_error(bank_account_id, _sanitize_error(str(exc)))
            raise
        finally:
            del rut, password, creds

        inserted = await _persist_movements(
            user_id=user_id,
            bank_account_id=bank_account_id,
            movements=result.movements,
        )

        await _update_account_after_sync(
            bank_account_id=bank_account_id,
            balance=result.balance.balance_clp if result.balance else None,
            sync_count=int(row["sync_count"] or 0),
        )

        if settings.sync_aria_enabled and inserted > 0:
            try:
                anon_profile = await _load_anon_profile(user_id)
                for m in result.movements[:inserted]:
                    from sky.domain.aria import track_spending_event
                    await track_spending_event(
                        anon_profile,
                        {"amount": m.amount_clp, "category": "other", "source": "bank_sync"},
                        user_id,
                    )
            except Exception as exc:
                logger.warning("aria_track_failed", error=str(exc))

        if inserted > 0:
            await arq_pool.enqueue_job("categorize_pending_job")

        elapsed_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
        logger.info(
            "sync_completed",
            bank_account_id=bank_account_id, bank_id=bank_id,
            new_transactions=inserted, elapsed_ms=elapsed_ms,
        )

        return {
            "success": True,
            "new_transactions": inserted,
            "balance": result.balance.balance_clp if result.balance else None,
            "bank_id": bank_id,
            "elapsed_ms": elapsed_ms,
        }


async def _persist_movements(
    *, user_id: str, bank_account_id: str, movements: list[Any],
) -> int:
    """
    Inserta movimientos con `categorization_status='pending'`. Idempotente vía
    UNIQUE INDEX (user_id, bank_account_id, external_id). Devuelve el conteo
    real de filas insertadas.
    """
    if not movements:
        return 0
    engine = get_engine()
    inserted = 0
    async with engine.begin() as conn:
        for m in movements:
            res = await conn.execute(
                text("""
                    INSERT INTO public.transactions
                        (user_id, bank_account_id, amount, category, description,
                         raw_description, date, external_id, movement_source,
                         categorization_status)
                    VALUES
                        (:user_id, :bank_account_id, :amount, 'other', 'Procesando...',
                         :raw_description, :date, :external_id, :movement_source,
                         'pending')
                    ON CONFLICT (user_id, bank_account_id, external_id)
                    WHERE external_id IS NOT NULL
                    DO NOTHING
                """),
                {
                    "user_id":         user_id,
                    "bank_account_id": bank_account_id,
                    "amount":          m.amount_clp,
                    "raw_description": m.raw_description,
                    "date":            m.occurred_at,
                    "external_id":     m.external_id,
                    "movement_source": m.movement_source.value,
                },
            )
            if res.rowcount and res.rowcount > 0:
                inserted += 1
    return inserted


async def _update_account_after_sync(
    *, bank_account_id: str, balance: int | None, sync_count: int,
) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE public.bank_accounts
                   SET last_sync_at = NOW(),
                       last_sync_error = NULL,
                       last_balance = COALESCE(:balance, last_balance),
                       status = 'active',
                       sync_count = :sync_count,
                       consecutive_errors = 0,
                       updated_at = NOW()
                 WHERE id = :id
            """),
            {"id": bank_account_id, "balance": balance, "sync_count": sync_count + 1},
        )


async def _mark_error(bank_account_id: str, msg: str) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE public.bank_accounts
                   SET status = 'error',
                       last_sync_error = :msg,
                       consecutive_errors = COALESCE(consecutive_errors, 0) + 1,
                       updated_at = NOW()
                 WHERE id = :id
            """),
            {"id": bank_account_id, "msg": msg[:500]},
        )


async def _load_anon_profile(user_id: str) -> Any:
    from sky.domain.aria import build_anon_profile
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text(
                "SELECT age_range, region, income_range, occupation"
                " FROM public.profiles WHERE id = :uid"
            ),
            {"uid": user_id},
        )
        row = rs.mappings().first()
    profile_dict: dict[str, Any] = dict(row) if row else {}
    return build_anon_profile(profile_dict)


def _sanitize_error(msg: str) -> str:
    """Eliminar PII y stack traces antes de mostrar al usuario."""
    if not msg:
        return "Error de sincronización"
    if re.search(r"password|rut|clave|credential", msg, re.I):
        return "Error de autenticación bancaria"
    if re.search(r"ETIMEDOUT|ECONNREFUSED|timeout", msg, re.I):
        return "El banco no respondió. Intenta más tarde."
    return msg[:200]
