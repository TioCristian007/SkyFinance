"""sky.api.routers.transactions — GET + PATCH + DELETE de transacciones."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from sky.api.deps import require_user_id
from sky.api.schemas.transactions import (
    MerchantRenameRequest,
    MerchantRenameResponse,
    RecategorizeRequest,
    TransactionListResponse,
    TransactionOut,
    TransactionPatchResponse,
)
from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.domain.categorizer import (
    CATEGORIES,
    merchant_display_batch,
    normalize_merchant,
)
from sky.domain.merchant_feedback import (
    record_user_categorization,
    record_user_rename,
)

logger = get_logger("api.transactions")
router = APIRouter(prefix="/api/transactions", tags=["transactions"])

# Canon único (16): el set anterior aceptaba 'travel' (violaba el CHECK de la
# DB → 500 al elegir "Viajes") y rechazaba 'insurance' (DB-válida) con 422.
_VALID_CATEGORIES = set(CATEGORIES)


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    user_id: str = Depends(require_user_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
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

    # Display con aliases (Fase 2): propio del usuario → global → Title Case.
    raws = [str(r["raw_description"]) if r["raw_description"] else None for r in rows]
    merchants = await merchant_display_batch(user_id, raws)

    txs = [
        TransactionOut(
            id=str(r["id"]),
            amount=int(r["amount"]),
            category=str(r["category"] or "other"),
            description=str(r["description"] or ""),
            raw_description=str(r["raw_description"] or ""),
            date=r["date"],
            bank_account_id=str(r["bank_account_id"]) if r["bank_account_id"] is not None else None,
            movement_source=str(r["movement_source"] or ""),
            categorization_status=str(r["categorization_status"] or "pending"),
            merchant=merchants[i],
        )
        for i, r in enumerate(rows)
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
                 RETURNING raw_description
            """),
            {"cat": body.category, "id": tx_id, "uid": user_id},
        )
        row = rs.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Transacción no encontrada")

    # Feedback loop: recategorizar enseña. Best-effort en transacción aparte —
    # la recategorización del usuario nunca falla porque el aprendizaje falló.
    try:
        await record_user_categorization(
            user_id=user_id,
            raw_description=str(row.raw_description or ""),
            category=body.category,
        )
    except Exception as exc:
        logger.warning("merchant_vote_failed", tx_id=tx_id, error=str(exc))

    logger.info("tx_recategorized", tx_id=tx_id, category=body.category)
    return TransactionPatchResponse(id=tx_id, category=body.category)


@router.patch("/{tx_id}/merchant", response_model=MerchantRenameResponse)
async def rename_merchant(
    tx_id: str,
    body: MerchantRenameRequest,
    user_id: str = Depends(require_user_id),
) -> MerchantRenameResponse:
    """Renombra el comercio de una tx (sprint Fase 2).

    La tx NO se muta: el display se deriva al leer (merchant_display_batch),
    así el renombre aplica de inmediato a TODAS las tx del mismo comercio.
    La raw_description se toma de la tx del propio usuario — el cliente
    nunca manda keys arbitrarias.
    """
    name = (body.display_name or "").strip()
    if not 1 <= len(name) <= 60:
        raise HTTPException(
            status_code=422,
            detail="El nombre debe tener entre 1 y 60 caracteres",
        )

    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT raw_description, category
                  FROM public.transactions
                 WHERE id = :id AND user_id = :uid AND deleted_at IS NULL
            """),
            {"id": tx_id, "uid": user_id},
        )
        row = rs.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Transacción no encontrada")

    raw = str(row.raw_description or "")
    if not normalize_merchant(raw):
        raise HTTPException(
            status_code=422,
            detail="Esta transacción no tiene comercio renombrable",
        )

    # A diferencia del voto de categoría (best-effort tras el UPDATE), acá
    # el alias ES la acción: si falla, el request falla.
    eligible = await record_user_rename(
        user_id=user_id,
        raw_description=raw,
        current_category=str(row.category or "other"),
        display_name=name,
    )

    logger.info("tx_merchant_renamed", tx_id=tx_id, eligible=eligible)
    return MerchantRenameResponse(
        id=tx_id, merchant=name, crowdsource_eligible=eligible,
    )


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
