"""sky.api.routers.summary — GET summary financiero del período."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from sky.api.deps import require_user_id
from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.domain.finance import NON_CONSUMPTION, compute_summary
from sky.ingestion.sources import SUPPORTED_BANKS, account_type_for

logger = get_logger("api.summary")
router = APIRouter(prefix="/api/summary", tags=["summary"])

_BANK_META: dict[str, dict[str, object]] = {b["id"]: b for b in SUPPORTED_BANKS}


@router.get("")
async def get_summary(
    user_id: str = Depends(require_user_id),
    days: int = Query(30, ge=1, le=365),
) -> dict[str, Any]:
    """
    Shape compatible con Node financeService.getSummary() +
    getUserProfile() + evaluateBadges().

    El frontend (Sky.jsx) desestructura summaryRes.summary,
    summaryRes.profile y summaryRes.badges.allBadges.
    """
    try:
        now_cl = datetime.now(ZoneInfo("America/Santiago"))
    except Exception:
        logger.warning("tz_data_unavailable_falling_back_to_utc")
        now_cl = datetime.now(UTC)
    since: date = now_cl.date().replace(day=1)
    engine = get_engine()

    txs, bank_rows, profile_row = await _fetch_all(engine, user_id, since)

    fin = compute_summary(txs, period_days=days)

    # ── Rates (0-100 integers, base = expenses/income consumo) ──────────────
    # Ambas tasas usan la misma base (expenses = consumo), haciéndolas complementarias:
    # spendingRate + savingsRate ≈ 100.
    spending_rate = int(max(0, round((fin.expenses / fin.income) * 100))) if fin.income > 0 else 0
    savings_rate  = int(max(0, round(fin.savings_rate * 100)))

    # ── categoryTotals (dict category→amount, igual que Node) ────────────────
    category_totals: dict[str, int] = dict(fin.by_category)

    # ── topCategory ──────────────────────────────────────────────────────────
    top_cat: dict[str, Any] | None = None
    if category_totals:
        best = max(category_totals.items(), key=lambda kv: kv[1])
        top_cat = {"category": best[0], "amount": best[1]}

    # ── period (ej: "2026-05") ────────────────────────────────────────────────
    now = datetime.now(tz=UTC)
    period = f"{now.year}-{now.month:02d}"

    # ── bankAccounts (camelCase, igual que banking router) ───────────────────
    bank_accounts = []
    total_bank_balance = 0
    for r in bank_rows:
        meta = _BANK_META.get(str(r["bank_id"]), {})
        last_sync_at = r["last_sync_at"]
        minutes_ago: int | None = None
        if last_sync_at:
            if last_sync_at.tzinfo is None:
                last_sync_at = last_sync_at.replace(tzinfo=UTC)
            minutes_ago = int((now - last_sync_at).total_seconds() / 60)
        balance = int(r["last_balance"] or 0)
        total_bank_balance += balance
        bank_id = str(r["bank_id"])
        bank_accounts.append({
            "id":            str(r["id"]),
            "bankId":        bank_id,
            "bankName":      meta.get("name", str(r["bank_name"] or bank_id)),
            "bankIcon":      meta.get("icon", str(r["bank_icon"] or "🏦")),
            "balance":       balance,
            "lastSyncAt":    r["last_sync_at"].isoformat() if r["last_sync_at"] else None,
            "lastSyncError": r["last_sync_error"],
            "status":        str(r["status"] or "active"),
            "syncCount":     int(r["sync_count"] or 0),
            "minutesAgo":    minutes_ago,
            "accountType":   account_type_for(bank_id),
            "last4":         None,
        })

    has_bank_accounts = len(bank_accounts) > 0

    # Conteos para KPIs del dashboard (sobre el universo completo del mes, no las 20 últimas txs)
    income_count = sum(1 for tx in txs if str(tx.get("category", "")) == "income")
    expense_count = sum(
        1 for tx in txs
        if int(tx.get("amount", 0)) < 0
        and str(tx.get("category", "")) not in NON_CONSUMPTION
    )

    income_is_real = has_bank_accounts and fin.income > 0

    # ── profile ──────────────────────────────────────────────────────────────
    display_name = "Usuario"
    points = 0
    if profile_row:
        display_name = profile_row.get("display_name") or "Usuario"
        points = int(profile_row.get("points") or 0)

    return {
        "summary": {
            "balance":          fin.net_flow,
            "income":           fin.income,
            "expenses":         fin.expenses,
            "savingsRate":      savings_rate,
            "spendingRate":     spending_rate,
            "categoryTotals":   category_totals,
            "transactionCount": len(txs),
            "incomeCount":      income_count,
            "expenseCount":     expense_count,
            "topCategory":      top_cat,
            "period":           period,
            "currency":         "CLP",
            "incomeIsReal":     income_is_real,
            "bankAccounts":     bank_accounts,
            "totalBankBalance": total_bank_balance,
            "hasBankAccounts":  has_bank_accounts,
        },
        "profile": {
            "user": {
                "id":       user_id,
                "name":     display_name,
                "currency": "CLP",
            },
            "points":        points,
            "level":         int(points / 100) + 1,
            "levelProgress": points % 100,
        },
        "badges": {
            "allBadges":  [],
            "newBadges":  [],
        },
    }


async def _fetch_all(
    engine: Any,
    user_id: str,
    since: date,
) -> tuple[list[dict[str, Any]], list[Any], dict[str, Any] | None]:
    """Queries paralelas: transactions + bank_accounts + profiles."""
    async with engine.connect() as conn:
        tx_rs, ba_rs, prof_rs = await _run_queries(conn, user_id, since)
        txs = [dict(r) for r in tx_rs.mappings().all()]
        bank_rows = ba_rs.mappings().all()
        profile_row_raw = prof_rs.mappings().first()
        profile_row = dict(profile_row_raw) if profile_row_raw else None
    return txs, bank_rows, profile_row


async def _run_queries(
    conn: Any,
    user_id: str,
    since: date,
) -> tuple[Any, Any, Any]:
    tx_rs = await conn.execute(
        text("""
            SELECT amount, category, bank_account_id
              FROM public.transactions
             WHERE user_id = :uid
               AND date >= :since
               AND deleted_at IS NULL
               AND categorization_status != 'pending'
               AND (bank_account_id IS NULL
                    OR bank_account_id IN (
                        SELECT id FROM public.bank_accounts
                         WHERE user_id = :uid AND status != 'disconnected'
                    ))
        """),
        {"uid": user_id, "since": since},
    )
    ba_rs = await conn.execute(
        text("""
            SELECT id, bank_id, bank_name, bank_icon, last_balance,
                   last_sync_at, last_sync_error, status, sync_count
              FROM public.bank_accounts
             WHERE user_id = :uid AND status != 'disconnected'
             ORDER BY created_at ASC
        """),
        {"uid": user_id},
    )
    prof_rs = await conn.execute(
        text("""
            SELECT display_name, points
              FROM public.profiles
             WHERE id = :uid
             LIMIT 1
        """),
        {"uid": user_id},
    )
    return tx_rs, ba_rs, prof_rs
