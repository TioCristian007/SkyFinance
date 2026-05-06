"""sky.api.routers.banking — Endpoints bancarios."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from sky.api.deps import require_user_id
from sky.api.schemas.banking import (
    BankAccountConnectedResponse,
    BankAccountConnectRequest,
    BankAccountListResponse,
    BankAccountOut,
    SyncAllResponse,
    SyncBankAccountResponse,
)
from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.encryption import encrypt
from sky.core.logging import get_logger
from sky.ingestion.sources import SUPPORTED_BANKS

logger = get_logger("api.banking")
router = APIRouter(prefix="/api/banking", tags=["banking"])

_BANK_META: dict[str, dict[str, object]] = {b["id"]: b for b in SUPPORTED_BANKS}


@router.post("/sync/{account_id}", response_model=SyncBankAccountResponse)
async def sync_bank_account_endpoint(
    account_id: str,
    request: Request,
    user_id: str = Depends(require_user_id),
) -> SyncBankAccountResponse:
    """
    Encola un sync de la cuenta indicada. Responde inmediato {started: true}.
    El frontend hace polling sobre /api/banking/accounts (Fase 7) para el progreso.
    """
    arq_pool = request.app.state.arq_pool
    job = await arq_pool.enqueue_job("sync_bank_account_job", account_id, user_id)
    if job is None:
        raise HTTPException(status_code=503, detail="No se pudo encolar el sync. Reintenta.")
    return SyncBankAccountResponse(started=True, job_id=job.job_id)


@router.post("/sync-all", response_model=SyncAllResponse)
async def sync_all_endpoint(
    request: Request,
    user_id: str = Depends(require_user_id),
) -> SyncAllResponse:
    """Encola un sync de TODAS las cuentas activas del user."""
    arq_pool = request.app.state.arq_pool
    job = await arq_pool.enqueue_job("sync_all_user_accounts_job", user_id)
    if job is None:
        raise HTTPException(status_code=503, detail="No se pudo encolar el sync. Reintenta.")
    return SyncAllResponse(started=True, job_id=job.job_id)


@router.get("/accounts", response_model=BankAccountListResponse)
async def list_accounts(
    user_id: str = Depends(require_user_id),
) -> BankAccountListResponse:
    """Lista cuentas activas del user con last_balance, last_sync_at, status."""
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id, bank_id, last_balance, last_sync_at,
                       last_sync_error, status, sync_count
                  FROM public.bank_accounts
                 WHERE user_id = :uid AND status != 'disconnected'
                 ORDER BY created_at ASC
            """),
            {"uid": user_id},
        )
        rows = rs.mappings().all()

    now = datetime.now(tz=UTC)
    accounts = []
    total_balance = 0
    for r in rows:
        meta = _BANK_META.get(str(r["bank_id"]), {})
        last_sync_at = r["last_sync_at"]
        minutes_ago: int | None = None
        if last_sync_at:
            if last_sync_at.tzinfo is None:
                last_sync_at = last_sync_at.replace(tzinfo=UTC)
            minutes_ago = int((now - last_sync_at).total_seconds() / 60)

        balance = int(r["last_balance"] or 0)
        total_balance += balance
        accounts.append(BankAccountOut(
            id=str(r["id"]),
            bank_id=str(r["bank_id"]),
            bank_name=meta.get("name", str(r["bank_id"])),
            bank_icon=meta.get("icon"),
            last_balance=balance,
            last_sync_at=r["last_sync_at"],
            last_sync_error=r["last_sync_error"],
            status=str(r["status"] or "active"),
            sync_count=int(r["sync_count"] or 0),
            minutes_ago=minutes_ago,
        ))

    return BankAccountListResponse(accounts=accounts, total_balance=total_balance)


@router.post("/accounts", response_model=BankAccountConnectedResponse, status_code=201)
async def connect_account(
    body: BankAccountConnectRequest,
    request: Request,
    user_id: str = Depends(require_user_id),
) -> BankAccountConnectedResponse:
    """
    Onboarding de cuenta bancaria.
    Cifra credenciales, persiste, encola primer sync.
    NUNCA logea rut/password.
    """
    if body.bank_id not in _BANK_META:
        raise HTTPException(
            status_code=422,
            detail=f"Banco no soportado: {body.bank_id}. "
                   f"Bancos disponibles: {list(_BANK_META)}",
        )

    bank_name = body.bank_name or _BANK_META[body.bank_id]["name"]
    enc_rut = encrypt(body.rut, settings.bank_encryption_key)
    enc_pass = encrypt(body.password, settings.bank_encryption_key)

    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("""
                INSERT INTO public.bank_accounts
                    (user_id, bank_id, bank_name, encrypted_rut, encrypted_pass,
                     status, sync_count, consecutive_errors)
                VALUES
                    (:uid, :bank_id, :bank_name, :enc_rut, :enc_pass,
                     'active', 0, 0)
                RETURNING id
            """),
            {
                "uid": user_id,
                "bank_id": body.bank_id,
                "bank_name": bank_name,
                "enc_rut": enc_rut,
                "enc_pass": enc_pass,
            },
        )
        row = rs.mappings().first()
        if row is None:
            raise HTTPException(status_code=500, detail="No se pudo crear la cuenta bancaria")
        account_id = str(row["id"])

    arq_pool = request.app.state.arq_pool
    job = await arq_pool.enqueue_job("sync_bank_account_job", account_id, user_id)
    sync_job_id = job.job_id if job else "queued"

    logger.info("bank_account_connected", bank_id=body.bank_id, account_id=account_id)
    return BankAccountConnectedResponse(
        id=account_id,
        bank_id=body.bank_id,
        status="active",
        sync_job_id=sync_job_id,
    )


@router.delete("/accounts/{account_id}", status_code=204)
async def disconnect_account(
    account_id: str,
    user_id: str = Depends(require_user_id),
) -> None:
    """Soft-disconnect: status='disconnected', no borra histórico de transactions."""
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("""
                UPDATE public.bank_accounts
                   SET status = 'disconnected', updated_at = NOW()
                 WHERE id = :id AND user_id = :uid AND status != 'disconnected'
            """),
            {"id": account_id, "uid": user_id},
        )
        if rs.rowcount == 0:
            raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    logger.info("bank_account_disconnected", account_id=account_id)
