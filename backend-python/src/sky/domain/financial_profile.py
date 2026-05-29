"""sky.domain.financial_profile — Perfil cualitativo privado por usuario.

Tabla: public.user_financial_profile (solo service_role).
El usuario nunca ve este perfil directamente. Mr. Money lo lee para
enriquecer el contexto y lo escribe via tools cuando detecta señales fuertes.
"""
from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from sky.api.schemas.profile_aria import FinancialProfile
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("financial_profile")

# Columnas que Mr. Money puede actualizar via tool.
_EDITABLE_DIMENSIONS: frozenset[str] = frozenset({
    "savings_mindset",
    "savings_mindset_conf",
    "risk_tolerance",
    "risk_tolerance_conf",
    "financial_volatility",
    "financial_volatility_conf",
    "goal_orientation",
    "goal_orientation_conf",
    "stress_baseline",
    "stress_current",
    "motivation_primary",
    "motivation_primary_conf",
    "recurring_blockers",
    "protective_behaviors",
})

# Máximo de observaciones emocionales a retener en el jsonb history.
_MAX_EMOTION_HISTORY = 20


async def get_profile(user_id: str) -> FinancialProfile | None:
    """Lee el perfil cualitativo del usuario. Devuelve None si aún no existe."""
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            rs = await conn.execute(
                text("""
                    SELECT savings_mindset, savings_mindset_conf,
                           risk_tolerance, risk_tolerance_conf,
                           financial_volatility, financial_volatility_conf,
                           goal_orientation, goal_orientation_conf,
                           stress_baseline, stress_current,
                           emotional_volatility, last_emotion, last_emotion_at,
                           motivation_primary, motivation_primary_conf,
                           recurring_blockers, protective_behaviors, updates_count
                      FROM public.user_financial_profile
                     WHERE user_id = :uid
                """),
                {"uid": user_id},
            )
            row = rs.mappings().first()
        if row is None:
            return None
        return FinancialProfile(**{k: v for k, v in row.items()})
    except Exception as exc:
        logger.warning("get_profile_failed", user_id=user_id, error=str(exc))
        return None


async def upsert_profile_dimension(
    user_id: str,
    dimension: str,
    value: Any,
    confidence: float,
) -> None:
    """
    Escribe una sola dimensión del perfil. Crea la fila si no existe (upsert).
    Solo dimensiones en _EDITABLE_DIMENSIONS son permitidas.
    """
    if dimension not in _EDITABLE_DIMENSIONS:
        raise ValueError(f"Dimensión '{dimension}' fuera del allow-list de edición")

    conf_col = f"{dimension}_conf"
    has_conf = conf_col in _EDITABLE_DIMENSIONS or conf_col in {
        "savings_mindset_conf", "risk_tolerance_conf", "financial_volatility_conf",
        "goal_orientation_conf", "motivation_primary_conf",
    }

    engine = get_engine()
    try:
        async with engine.begin() as conn:
            if has_conf:
                await conn.execute(
                    text(f"""
                        INSERT INTO public.user_financial_profile
                            (user_id, {dimension}, {conf_col},
                             updates_count, first_observed_at, last_updated_at)
                        VALUES
                            (:uid, :val, :conf, 1, NOW(), NOW())
                        ON CONFLICT (user_id) DO UPDATE SET
                            {dimension}    = EXCLUDED.{dimension},
                            {conf_col}     = EXCLUDED.{conf_col},
                            updates_count  =
                                public.user_financial_profile.updates_count + 1,
                            last_updated_at = NOW()
                    """),
                    {"uid": user_id, "val": value, "conf": confidence},
                )
            else:
                # Dimensiones jsonb (recurring_blockers, protective_behaviors)
                val_sql = json.dumps(value) if isinstance(value, (list, dict)) else value
                await conn.execute(
                    text(f"""
                        INSERT INTO public.user_financial_profile
                            (user_id, {dimension},
                             updates_count, first_observed_at, last_updated_at)
                        VALUES
                            (:uid, :val, 1, NOW(), NOW())
                        ON CONFLICT (user_id) DO UPDATE SET
                            {dimension}    = EXCLUDED.{dimension},
                            updates_count  =
                                public.user_financial_profile.updates_count + 1,
                            last_updated_at = NOW()
                    """),
                    {"uid": user_id, "val": val_sql},
                )
    except Exception as exc:
        logger.warning(
            "upsert_dimension_failed", user_id=user_id, dimension=dimension, error=str(exc)
        )


async def apply_emotion_inference(
    user_id: str,
    emotion: str,
    intensity: int,
    signal_kind: str,
) -> None:
    """
    Registra una inferencia emocional y actualiza:
    - last_emotion / last_emotion_at
    - stress_current (mapeado desde intensity)
    - emotional_volatility (rolling std de últimas _MAX_EMOTION_HISTORY observaciones)
    - emotion_history (jsonb, últimas _MAX_EMOTION_HISTORY entradas)
    """
    engine = get_engine()
    try:
        # Leer emotion_history actual
        async with engine.connect() as conn:
            rs = await conn.execute(
                text(
                    "SELECT emotion_history"
                    " FROM public.user_financial_profile WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
            row = rs.mappings().first()

        history: list[int] = []
        if row and row["emotion_history"]:
            raw = row["emotion_history"]
            parsed = raw if isinstance(raw, list) else json.loads(raw)
            history = [int(x) for x in parsed if isinstance(x, (int, float))]

        history.append(intensity)
        if len(history) > _MAX_EMOTION_HISTORY:
            history = history[-_MAX_EMOTION_HISTORY:]

        volatility: int | None = None
        if len(history) >= 2:
            volatility = min(10, round(statistics.stdev(history)))

        now = datetime.now(UTC)
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO public.user_financial_profile
                        (user_id, last_emotion, last_emotion_at, stress_current,
                         emotional_volatility, emotion_history, updates_count,
                         first_observed_at, last_updated_at)
                    VALUES
                        (:uid, :emotion, :now, :stress, :volatility,
                         CAST(:history AS jsonb), 1, NOW(), NOW())
                    ON CONFLICT (user_id) DO UPDATE SET
                        last_emotion        = EXCLUDED.last_emotion,
                        last_emotion_at     = EXCLUDED.last_emotion_at,
                        stress_current      = EXCLUDED.stress_current,
                        emotional_volatility = COALESCE(EXCLUDED.emotional_volatility,
                                               public.user_financial_profile.emotional_volatility),
                        emotion_history     = EXCLUDED.emotion_history,
                        updates_count       = public.user_financial_profile.updates_count + 1,
                        last_updated_at     = NOW()
                """),
                {
                    "uid":        user_id,
                    "emotion":    emotion,
                    "now":        now,
                    "stress":     min(10, max(0, intensity)),
                    "volatility": volatility,
                    "history":    json.dumps(history),
                },
            )
        logger.info(
            "emotion_inferred",
            user_id=user_id,
            emotion=emotion,
            intensity=intensity,
            signal_kind=signal_kind,
            volatility=volatility,
        )
    except Exception as exc:
        logger.warning("apply_emotion_failed", user_id=user_id, error=str(exc))
