"""sky.domain.goals — CRUD de metas + proyección mensual."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from sky.core.db import get_engine
from sky.domain.finance import compute_summary


def calc_goal_projection(
    current_amount: int,
    target_amount: int,
    monthly_capacity: int,
) -> dict[str, Any]:
    """
    Calcula proyección de meta financiera.
    Paridad con calcGoalProjection() de financeService.js.
    """
    target = max(1, target_amount)
    remaining = max(0, target - current_amount)
    pct = round(current_amount / target * 100)
    monthly = max(0, monthly_capacity)

    months_to_goal: int | None = None
    projected_date: str | None = None

    if monthly > 0 and remaining > 0:
        months_to_goal = math.ceil(remaining / monthly)
        projected_date = (date.today() + timedelta(days=months_to_goal * 30)).isoformat()

    return {
        "pct": min(pct, 100),
        "remaining": remaining,
        "monthly_savings": monthly,
        "months_to_goal": months_to_goal,
        "projected_date": projected_date,
    }


async def _get_monthly_capacity(user_id: str) -> int:
    """Calcula capacity = max(0, ingreso - gastos) de los últimos 30 días."""
    since = date.today() - timedelta(days=30)
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT amount, category
                  FROM public.transactions
                 WHERE user_id = :uid
                   AND date >= :since
                   AND deleted_at IS NULL
            """),
            {"uid": user_id, "since": since},
        )
        txs: list[dict[str, Any]] = [dict(r) for r in rs.mappings().all()]
    summary = compute_summary(txs)
    return int(max(0, summary.income - summary.expenses))


async def get_goals(user_id: str) -> list[dict[str, Any]]:
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id, name, target_amount, current_amount, target_date, created_at
                  FROM public.goals
                 WHERE user_id = :uid
                 ORDER BY created_at ASC
            """),
            {"uid": user_id},
        )
        rows = [dict(r) for r in rs.mappings().all()]

    monthly = await _get_monthly_capacity(user_id)
    return [
        {
            **row,
            "progress_pct": float(calc_goal_projection(
                int(row["current_amount"] or 0),
                int(row["target_amount"] or 1),
                monthly,
            )["pct"]),
            "projection": calc_goal_projection(
                int(row["current_amount"] or 0),
                int(row["target_amount"] or 1),
                monthly,
            ),
        }
        for row in rows
    ]


async def create_goal(
    user_id: str,
    name: str,
    target_amount: int,
    target_date: date | None,
) -> dict[str, Any]:
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("""
                INSERT INTO public.goals
                    (user_id, name, target_amount, current_amount, target_date)
                VALUES (:uid, :name, :target, 0, :target_date)
                RETURNING id, name, target_amount, current_amount, target_date, created_at
            """),
            {"uid": user_id, "name": name, "target": target_amount, "target_date": target_date},
        )
        row = rs.mappings().first()
        if row is None:
            raise RuntimeError("Error al crear la meta")
        result = dict(row)

    monthly = await _get_monthly_capacity(user_id)
    result["progress_pct"] = float(calc_goal_projection(
        int(result["current_amount"] or 0),
        int(result["target_amount"] or 1),
        monthly,
    )["pct"])
    return result


async def update_goal(
    user_id: str,
    goal_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    allowed = {"name", "target_amount", "target_date", "current_amount"}
    set_parts = []
    params: dict[str, Any] = {"id": goal_id, "uid": user_id}

    for key in allowed:
        if key in updates and updates[key] is not None:
            set_parts.append(f"{key} = :{key}")
            params[key] = updates[key]

    if not set_parts:
        return None

    set_parts.append("updated_at = NOW()")
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text(
                f"UPDATE public.goals SET {', '.join(set_parts)}"
                " WHERE id = :id AND user_id = :uid"
                " RETURNING id, name, target_amount, current_amount, target_date, created_at"
            ),
            params,
        )
        row = rs.mappings().first()
        if row is None:
            return None
        result = dict(row)

    monthly = await _get_monthly_capacity(user_id)
    result["progress_pct"] = float(calc_goal_projection(
        int(result["current_amount"] or 0),
        int(result["target_amount"] or 1),
        monthly,
    )["pct"])
    return result


async def delete_goal(user_id: str, goal_id: str) -> bool:
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("DELETE FROM public.goals WHERE id = :id AND user_id = :uid"),
            {"id": goal_id, "uid": user_id},
        )
        return bool(rs.rowcount and rs.rowcount > 0)
