"""sky.api.routers.summary — GET summary financiero del período."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from sky.api.deps import require_user_id
from sky.api.schemas.summary import (
    CategoryBreakdown,
    SummaryByCategoryResponse,
    SummaryResponse,
)
from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.domain.finance import CATEGORY_LABELS, compute_summary, top_categories

logger = get_logger("api.summary")
router = APIRouter(prefix="/api/summary", tags=["summary"])


@router.get("", response_model=SummaryResponse)
async def get_summary(
    user_id: str = Depends(require_user_id),
    days: int = Query(30, ge=1, le=365),
) -> SummaryResponse:
    txs = await _fetch_transactions(user_id, days)
    summary = compute_summary(txs, period_days=days)
    return SummaryResponse(
        balance=summary.balance,
        income=summary.income,
        expenses=summary.expenses,
        savings_rate=round(summary.savings_rate, 4),
        net_flow=summary.net_flow,
        period_days=days,
    )


@router.get("/by-category", response_model=SummaryByCategoryResponse)
async def summary_by_category(
    user_id: str = Depends(require_user_id),
    days: int = Query(30, ge=1, le=365),
) -> SummaryByCategoryResponse:
    txs = await _fetch_transactions(user_id, days)
    summary = compute_summary(txs, period_days=days)
    cats = top_categories(summary.by_category, limit=20)
    return SummaryByCategoryResponse(
        categories=[
            CategoryBreakdown(
                category=c["category"],
                label=CATEGORY_LABELS.get(c["category"], c["category"]),
                amount=c["amount"],
                percentage=c["percentage"],
            )
            for c in cats
        ],
        total_expenses=summary.expenses,
    )


async def _fetch_transactions(user_id: str, days: int) -> list[dict[str, object]]:
    since = datetime.utcnow() - timedelta(days=days)
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT amount, category
                  FROM public.transactions
                 WHERE user_id = :uid
                   AND date >= :since
                   AND deleted_at IS NULL
                   AND categorization_status != 'pending'
            """),
            {"uid": user_id, "since": since.date()},
        )
        return [dict(r) for r in rs.mappings().all()]
