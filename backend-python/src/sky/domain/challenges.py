"""
sky.domain.challenges — CRUD de desafíos.

Desafíos viven en public.challenges con estados:
  proposed  → propuesto por Mr. Money, pendiente de confirmación del usuario
  active    → aceptado por el usuario
  completed → completado
  declined  → rechazado

propose_challenge NO crea en DB. Cuando el usuario acepta desde el frontend,
el router llama a create_challenge con status='active'.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from sky.core.db import get_engine


async def get_challenges(user_id: str) -> list[dict[str, Any]]:
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id, title, description, target_amount, current_amount,
                       start_date, end_date, status, created_at
                  FROM public.challenges
                 WHERE user_id = :uid
                 ORDER BY created_at DESC
            """),
            {"uid": user_id},
        )
        return [dict(r) for r in rs.mappings().all()]


async def create_challenge(
    user_id: str,
    title: str,
    description: str,
    target_amount: int,
    duration_days: int,
    status: str = "proposed",
) -> dict[str, Any]:
    """Persiste un desafío propuesto por Mr. Money. Status inicial: 'proposed'."""
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("""
                INSERT INTO public.challenges
                    (user_id, title, description, target_amount, current_amount,
                     start_date, end_date, status)
                VALUES
                    (:uid, :title, :description, :target, 0,
                     CURRENT_DATE, CURRENT_DATE + :days * INTERVAL '1 day', :status)
                RETURNING id, title, description, target_amount, current_amount,
                          start_date, end_date, status, created_at
            """),
            {
                "uid": user_id,
                "title": title,
                "description": description,
                "target": target_amount,
                "days": duration_days,
                "status": status,
            },
        )
        row = rs.mappings().first()
        if row is None:
            raise RuntimeError("Error al crear el desafío")
        return dict(row)


async def accept_challenge(user_id: str, challenge_id: str) -> dict[str, Any] | None:
    """Mueve estado proposed → active."""
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("""
                UPDATE public.challenges
                   SET status = 'active', updated_at = NOW()
                 WHERE id = :id AND user_id = :uid AND status = 'proposed'
                RETURNING id
            """),
            {"id": challenge_id, "uid": user_id},
        )
        row = rs.mappings().first()
        return dict(row) if row else None


async def decline_challenge(user_id: str, challenge_id: str) -> dict[str, Any] | None:
    """Mueve estado proposed → declined."""
    engine = get_engine()
    async with engine.begin() as conn:
        rs = await conn.execute(
            text("""
                UPDATE public.challenges
                   SET status = 'declined', updated_at = NOW()
                 WHERE id = :id AND user_id = :uid AND status = 'proposed'
                RETURNING id
            """),
            {"id": challenge_id, "uid": user_id},
        )
        row = rs.mappings().first()
        return dict(row) if row else None
