"""sky.domain.challenges — Desafíos financieros con MOCK_CHALLENGES + challenge_states."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text

from sky.core.db import get_engine

# Paridad exacta con MOCK_CHALLENGES de financeService.js
MOCK_CHALLENGES: list[dict[str, Any]] = [
    {"id": "no_uber",     "label": "Sin Uber 7 días",         "icon": "🚗", "desc": "No gastes en transporte esta semana", "category": "transport",     "limit_amt": 0,     "days": 7,  "pts": 150, "difficulty": "Medio"},
    {"id": "food_budget", "label": "Comida bajo $80K",         "icon": "🍔", "desc": "Gasta menos de $80.000 en comida",   "category": "food",          "limit_amt": 80000, "days": 30, "pts": 200, "difficulty": "Difícil"},
    {"id": "no_entert",   "label": "Sin entretención 5 días",  "icon": "🎮", "desc": "Pausa el gasto en ocio 5 días",      "category": "entertainment", "limit_amt": 0,     "days": 5,  "pts": 100, "difficulty": "Fácil"},
    {"id": "save_60k",    "label": "Ahorra $60K este mes",     "icon": "💰", "desc": "Reduce gastos para ahorrar $60.000", "category": None,            "limit_amt": 60000, "days": 30, "pts": 250, "difficulty": "Difícil"},
    {"id": "no_subs",     "label": "Cancela 1 suscripción",    "icon": "📺", "desc": "Elimina una suscripción que no usas","category": "subscriptions", "limit_amt": 0,     "days": 1,  "pts": 80,  "difficulty": "Fácil"},
    {"id": "daily_track", "label": "Registra 5 gastos",        "icon": "📝", "desc": "Anota 5 transacciones en la app",   "category": None,            "limit_amt": 5,     "days": 7,  "pts": 120, "difficulty": "Fácil"},
]


def _current_period() -> str:
    d = date.today()
    return f"{d.year}-{str(d.month).zfill(2)}"


def calc_challenge_progress(
    challenge: dict[str, Any], transactions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Paridad con calcChallengeProgress() de financeService.js."""
    period = _current_period()
    in_month = [t for t in transactions if str(t.get("date", "")).startswith(period)]
    txs = [t for t in in_month if t.get("category") != "income"]

    cid = challenge["id"]
    limit_amt = challenge["limit_amt"]
    category = challenge["category"]

    if cid == "daily_track":
        done = min(len(transactions), 5)
        return {"pct": round(done / 5 * 100), "done": done >= 5}

    if cid == "save_60k":
        spent = sum(abs(t.get("amount") or 0) for t in txs)
        saved = max(0, 1_200_000 - spent)
        return {"pct": round(min(saved, 60000) / 60000 * 100), "done": saved >= 60000}

    if category and limit_amt == 0:
        spent = sum(abs(t.get("amount") or 0) for t in txs if t.get("category") == category)
        return {"pct": 100 if spent == 0 else 0, "done": spent == 0}

    if category and limit_amt > 0:
        spent = sum(abs(t.get("amount") or 0) for t in txs if t.get("category") == category)
        prog = max(0, limit_amt - spent)
        return {"pct": round(prog / limit_amt * 100), "done": spent > 0 and spent <= limit_amt}

    return {"pct": 0, "done": False}


async def _get_challenge_states(user_id: str) -> list[dict[str, Any]]:
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT challenge_id, status, points_earned
                  FROM public.challenge_states
                 WHERE user_id = :uid
            """),
            {"uid": user_id},
        )
        return [dict(r) for r in rs.mappings().all()]


async def _get_transactions(user_id: str) -> list[dict[str, Any]]:
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT amount, category, date
                  FROM public.transactions
                 WHERE user_id = :uid
                   AND categorization_status != 'pending'
            """),
            {"uid": user_id},
        )
        return [dict(r) for r in rs.mappings().all()]


async def get_challenges(user_id: str) -> dict[str, Any]:
    states = await _get_challenge_states(user_id)
    transactions = await _get_transactions(user_id)

    active_ids = {s["challenge_id"] for s in states if s["status"] == "active"}
    completed_ids = {s["challenge_id"] for s in states if s["status"] == "completed"}

    points = sum(s.get("points_earned") or 0 for s in states if s["status"] == "completed")

    active = [
        {**ch, "progress": calc_challenge_progress(ch, transactions)}
        for ch in MOCK_CHALLENGES if ch["id"] in active_ids
    ]
    completed = [ch for ch in MOCK_CHALLENGES if ch["id"] in completed_ids]
    available = [
        ch for ch in MOCK_CHALLENGES
        if ch["id"] not in active_ids and ch["id"] not in completed_ids
    ]

    return {"active": active, "completed": completed, "available": available, "points": points}


async def activate_challenge(user_id: str, challenge_id: str) -> dict[str, Any]:
    ch = next((c for c in MOCK_CHALLENGES if c["id"] == challenge_id), None)
    if ch is None:
        return {"error": "Desafío no encontrado"}

    states = await _get_challenge_states(user_id)
    if any(s["challenge_id"] == challenge_id for s in states):
        return {"error": "Desafío ya activo o completado"}

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO public.challenge_states (user_id, challenge_id, status)
                VALUES (:uid, :cid, 'active')
            """),
            {"uid": user_id, "cid": challenge_id},
        )
    return {"success": True, "challenge": ch}


async def complete_challenge(user_id: str, challenge_id: str) -> dict[str, Any]:
    ch = next((c for c in MOCK_CHALLENGES if c["id"] == challenge_id), None)
    if ch is None:
        return {"error": "Desafío no encontrado"}

    transactions = await _get_transactions(user_id)
    progress = calc_challenge_progress(ch, transactions)
    if not progress["done"]:
        return {"error": "Desafío aún no completado"}

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE public.challenge_states
                   SET status = 'completed',
                       completed_at = NOW(),
                       points_earned = :pts
                 WHERE user_id = :uid AND challenge_id = :cid
            """),
            {"uid": user_id, "cid": challenge_id, "pts": ch["pts"]},
        )
        rs = await conn.execute(
            text("SELECT points FROM public.profiles WHERE id = :uid"),
            {"uid": user_id},
        )
        row = rs.mappings().first()
        total = (row["points"] if row else 0) or 0

    return {
        "success": True, "challenge": ch,
        "points_earned": ch["pts"], "total_points": total + ch["pts"],
    }


async def accept_challenge(user_id: str, challenge_id: str) -> dict[str, Any] | None:
    result = await activate_challenge(user_id, challenge_id)
    if "error" in result:
        return None
    return {"id": challenge_id}


async def decline_challenge(user_id: str, challenge_id: str) -> dict[str, Any] | None:
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("""
                UPDATE public.challenge_states
                   SET status = 'declined'
                 WHERE user_id = :uid AND challenge_id = :cid AND status = 'active'
                RETURNING challenge_id AS id
            """),
            {"uid": user_id, "cid": challenge_id},
        )
        row = rs.mappings().first()
        return dict(row) if row else None
