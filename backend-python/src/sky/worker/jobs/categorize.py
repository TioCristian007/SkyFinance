"""
sky.worker.jobs.categorize — Procesamiento de cola de categorización.

Toma hasta CATEGORIZE_BATCH_SIZE filas con categorization_status='pending',
las pasa por las 3 capas, y aplica el resultado.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.domain.categorizer import categorize_movements

logger = get_logger("jobs.categorize")


async def categorize_pending_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """Job ARQ: categoriza hasta BATCH_SIZE filas pendientes."""
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id, raw_description, amount
                  FROM public.transactions
                 WHERE categorization_status = 'pending'
                 ORDER BY created_at ASC
                 LIMIT :batch
            """),
            {"batch": settings.categorize_batch_size},
        )
        rows = rs.mappings().all()

    if not rows:
        return {"processed": 0, "skipped": True}

    movements = [
        {"description": r["raw_description"] or "", "amount": int(r["amount"] or 0)}
        for r in rows
    ]
    items = await categorize_movements(movements)

    # items viene en el mismo orden que movements; rows en el mismo orden.
    succeeded = failed = 0
    async with engine.begin() as conn:
        for row, item in zip(rows, items, strict=True):
            is_fallback = item.category == "other" and item.source == "fallback"
            new_status = "failed" if is_fallback else "done"
            try:
                await conn.execute(
                    text("""
                        UPDATE public.transactions
                           SET category = :cat,
                               description = :label,
                               categorization_status = :status
                         WHERE id = :id
                    """),
                    {
                        "id":     row["id"],
                        "cat":    item.category,
                        "label":  item.label,
                        "status": new_status,
                    },
                )
                succeeded += 1
            except Exception as exc:
                logger.error("update_failed", id=str(row["id"]), error=str(exc))
                failed += 1

    logger.info("categorize_batch_done", processed=succeeded, failed=failed)
    return {"processed": succeeded, "failed": failed}
