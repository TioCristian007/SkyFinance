"""sky.api.routers.banking — Endpoints bancarios (Fase 6 = solo sync)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from sky.api.deps import require_user_id
from sky.api.schemas.banking import SyncAllResponse, SyncBankAccountResponse
from sky.core.logging import get_logger

logger = get_logger("api.banking")
router = APIRouter(prefix="/api/banking", tags=["banking"])


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
