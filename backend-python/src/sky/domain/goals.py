"""sky.domain.goals — CRUD de metas + proyección mensual."""
from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.domain.finance import compute_summary

logger = get_logger("goals")

_aria_tasks: set[asyncio.Task[None]] = set()


async def _fire_goal_aria(
    user_id: str,
    goal: dict[str, Any],
    completion_rate: float,
    goal_status: str,
) -> None:
    """Fire-and-forget: registrar evento de meta en ARIA."""
    try:
        from sky.domain.aria import build_anon_profile, track_goal_event
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
        profile = build_anon_profile(dict(row) if row else {})
        await track_goal_event(
            profile, goal,
            completion_rate=completion_rate, goal_status=goal_status,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning("aria_goal_fire_failed", error=str(exc))


def calc_goal_projection(
    current_amount: int,
    target_amount: int,
    monthly_capacity: int,
) -> dict[str, Any]:
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
                   AND categorization_status != 'pending'
            """),
            {"uid": user_id, "since": since},
        )
        txs: list[dict[str, Any]] = [dict(r) for r in rs.mappings().all()]
    summary = compute_summary(txs)
    return int(max(0, summary.net_flow))


async def get_goals(user_id: str) -> list[dict[str, Any]]:
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id,
                       title        AS name,
                       target_amount,
                       saved_amount AS current_amount,
                       deadline     AS target_date,
                       created_at
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
                    (user_id, title, target_amount, saved_amount, deadline)
                VALUES (:uid, :name, :target, 0, :target_date)
                RETURNING id,
                          title        AS name,
                          target_amount,
                          saved_amount AS current_amount,
                          deadline     AS target_date,
                          created_at
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

    _task = asyncio.create_task(
        _fire_goal_aria(user_id, result, completion_rate=0.0, goal_status="active")
    )
    _aria_tasks.add(_task)
    _task.add_done_callback(_aria_tasks.discard)

    return result


async def update_goal(
    user_id: str,
    goal_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    # Mapeo de nombres del request → nombres reales de columna
    field_map = {
        "name": "title",
        "current_amount": "saved_amount",
        "target_date": "deadline",
        "target_amount": "target_amount",
    }

    set_parts = []
    params: dict[str, Any] = {"id": goal_id, "uid": user_id}

    for request_key, db_col in field_map.items():
        if request_key in updates and updates[request_key] is not None:
            set_parts.append(f"{db_col} = :{db_col}")
            params[db_col] = updates[request_key]

    if not set_parts:
        return None

    set_parts.append("updated_at = NOW()")
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text(
                f"UPDATE public.goals SET {', '.join(set_parts)}"
                " WHERE id = :id AND user_id = :uid"
                " RETURNING id,"
                "           title        AS name,"
                "           target_amount,"
                "           saved_amount AS current_amount,"
                "           deadline     AS target_date,"
                "           created_at"
            ),
            params,
        )
        row = rs.mappings().first()
        if row is None:
            return None
        result = dict(row)

    monthly = await _get_monthly_capacity(user_id)
    pct = float(calc_goal_projection(
        int(result["current_amount"] or 0),
        int(result["target_amount"] or 1),
        monthly,
    )["pct"])
    result["progress_pct"] = pct

    goal_status = "completed" if pct >= 100 else "active"
    _task = asyncio.create_task(
        _fire_goal_aria(user_id, result, completion_rate=pct, goal_status=goal_status)
    )
    _aria_tasks.add(_task)
    _task.add_done_callback(_aria_tasks.discard)

    return result


async def delete_goal(user_id: str, goal_id: str) -> bool:
    engine = get_engine()
    async with engine.begin() as conn:
        pre = await conn.execute(
            text("""
                SELECT title AS name, target_amount, saved_amount AS current_amount
                  FROM public.goals WHERE id = :id AND user_id = :uid
            """),
            {"id": goal_id, "uid": user_id},
        )
        pre_row = pre.mappings().first()

        rs = await conn.execute(
            text("DELETE FROM public.goals WHERE id = :id AND user_id = :uid"),
            {"id": goal_id, "uid": user_id},
        )
        deleted = bool(rs.rowcount and rs.rowcount > 0)

    if deleted and pre_row:
        goal_dict = dict(pre_row)
        target = int(goal_dict.get("target_amount") or 1)
        current = int(goal_dict.get("current_amount") or 0)
        pct = min(100.0, round(current / target * 100, 1))
        _task = asyncio.create_task(
            _fire_goal_aria(user_id, goal_dict, completion_rate=pct, goal_status="abandoned")
        )
        _aria_tasks.add(_task)
        _task.add_done_callback(_aria_tasks.discard)

    return deleted
