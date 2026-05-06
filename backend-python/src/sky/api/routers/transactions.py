"""sky.api.routers.transactions — GET + PATCH + DELETE de transacciones."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from sky.api.deps import require_user_id
from sky.api.schemas.transactions import (
    RecategorizeRequest,
    TransactionListResponse,
    TransactionOut,
    TransactionPatchResponse,
)
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("api.transactions")
router = APIRouter(prefix="/api/transactions", tags=["transactions"])

_VALID_CATEGORIES = {
    "income", "food", "transport", "housing", "health", "entertainment",
    "shopping", "utilities", "subscriptions", "education", "travel",
    "banking_fee", "transfer", "debt_payment", "savings", "other",
}


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    user_id: str = Depends(require_user_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    bank_account_id: str | None = Query(None),
) -> TransactionListResponse:
    engine = get_engine()
    offset = (page - 1) * page_size

    where_parts = ["user_id = :uid", "deleted_at IS NULL"]
    params: dict[str, object] = {"uid": user_id, "limit": page_size, "offset": offset}

    if category:
        where_parts.append("category = :category")
        params["category"] = category
    if bank_account_id:
        where_parts.append("bank_account_id = :baid")
        params["baid"] = bank_account_id

    where_clause = " AND ".join(where_parts)

    async with engine.connect() as conn:
        count_rs = await conn.execute(
            text(f"SELECT COUNT(*) FROM public.transactions WHERE {where_clause}"),
            params,
        )
        total = count_rs.scalar() or 0

        rs = await conn.execute(
            text(f"""
                SELECT id, amount, category, description, raw_description,
                       date, bank_account_id, movement_source, categorization_status
                  FROM public.transactions
                 WHERE {where_clause}
                 ORDER BY date DESC, created_at DESC
                 LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = rs.mappings().all()

    txs = [
        TransactionOut(
            id=str(r["id"]),
            amount=int(r["amount"]),
            category=str(r["category"] or "other"),
            description=str(r["description"] or ""),
            raw_description=str(r["raw_description"] or ""),
            date=r["date"],
            bank_account_id=str(r["bank_account_id"]),
            movement_source=str(r["movement_source"] or ""),
            categorization_status=str(r["categorization_status"] or "pending"),
        )
        for r in rows
    ]
    return TransactionListResponse(
        transactions=txs, total=int(total), page=page, page_size=page_size,
    )


@router.patch("/{tx_id}", response_model=TransactionPatchResponse)
async def recategorize(
    tx_id: str,
    body: RecategorizeRequest,
    user_id: str = Depends(require_user_id),
) -> TransactionPatchResponse:
    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Categoría inválida: {body.category}")

    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("""
                UPDATE public.transactions
                   SET category = :cat,
                       categorization_status = 'done',
                       updated_at = NOW()
                 WHERE id = :id AND user_id = :uid AND deleted_at IS NULL
            """),
            {"cat": body.category, "id": tx_id, "uid": user_id},
        )
        if rs.rowcount == 0:
            raise HTTPException(status_code=404, detail="Transacción no encontrada")

    logger.info("tx_recategorized", tx_id=tx_id, category=body.category)
    return TransactionPatchResponse(id=tx_id, category=body.category)


@router.delete("/{tx_id}", status_code=204)
async def soft_delete(
    tx_id: str,
    user_id: str = Depends(require_user_id),
) -> Response:
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("""
                UPDATE public.transactions
                   SET deleted_at = NOW(), updated_at = NOW()
                 WHERE id = :id AND user_id = :uid AND deleted_at IS NULL
            """),
            {"id": tx_id, "uid": user_id},
        )
        if rs.rowcount == 0:
            raise HTTPException(status_code=404, detail="Transacción no encontrada")

    logger.info("tx_soft_deleted", tx_id=tx_id)
    return Response(status_code=204)
