"""sky.worker.jobs.snapshot_profiles — Snapshot semanal k-anon de perfiles cualitativos.

Trigger: lunes 03:00 America/Santiago (configurado en WorkerSettings.cron_jobs).
Lee public.user_financial_profile JOIN public.profiles (consent=true),
agrupa por bucket demográfico (AnonProfile), y para cada bucket con
count >= k_anon_min inserta un snapshot por perfil en aria.user_profile_snapshots.
Buckets bajo el umbral se omiten (silencioso + métrica).
"""
from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_aria_client, get_engine
from sky.core.logging import get_logger
from sky.domain.aria import (
    _get_period,
    _get_region_bucket,
    _normalize_age_range,
    _normalize_income_bucket,
    _normalize_occupation,
)

logger = get_logger("snapshot_profiles")


def _int_bucket(value: int | None, low_max: int = 3, high_min: int = 7) -> str | None:
    """Bucketiza un entero 0-10 en low/mid/high."""
    if value is None:
        return None
    if value <= low_max:
        return "low"
    if value >= high_min:
        return "high"
    return "mid"


async def snapshot_profiles_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Genera snapshots anonimizados de perfiles cualitativos con k-anonymity.

    Flujo:
    1. Lee user_financial_profile JOIN profiles (aria_consent=true) en una sola tx.
    2. Agrupa por (age_range, region, income_range, occupation) — el AnonProfile bucket.
    3. Para buckets con count >= k_anon_min: inserta un snapshot por usuario (sin user_id).
    4. Buckets < k_anon_min: skip silencioso + log.
    """
    engine = get_engine()
    period = _get_period()
    k_min = settings.profile_snapshot_k_anon_min
    jitter_days = settings.profile_snapshot_jitter_days

    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT
                    p.age_range,
                    p.region,
                    p.income_range,
                    p.occupation,
                    ufp.savings_mindset,
                    ufp.risk_tolerance,
                    ufp.financial_volatility,
                    ufp.goal_orientation,
                    ufp.stress_baseline,
                    ufp.motivation_primary,
                    ufp.emotional_volatility
                FROM public.user_financial_profile ufp
                JOIN public.profiles p ON p.id = ufp.user_id
                WHERE p.aria_consent = true
                  AND ufp.last_updated_at IS NOT NULL
            """),
        )
        rows = [dict(r) for r in rs.mappings().all()]

    if not rows:
        logger.info("snapshot_profiles_empty")
        return {"total": 0, "inserted": 0, "skipped_buckets": 0}

    # Agrupar por bucket demográfico
    buckets: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            _normalize_age_range(row.get("age_range")),
            _get_region_bucket(row.get("region")),
            _normalize_income_bucket(row.get("income_range")),
            _normalize_occupation(row.get("occupation")),
        )
        buckets.setdefault(key, []).append(row)

    batch_id = str(uuid4())
    inserted = 0
    skipped_buckets = 0
    snapshots: list[dict[str, Any]] = []

    for (age_range, region, income_range, occupation), profiles in buckets.items():
        if len(profiles) < k_min:
            skipped_buckets += 1
            logger.info(
                "snapshot_bucket_skipped",
                bucket=f"{age_range}/{region}/{income_range}/{occupation}",
                count=len(profiles),
                k_min=k_min,
            )
            continue

        for profile in profiles:
            snapshots.append({
                "age_range":                    age_range,
                "region":                       region,
                "income_range":                 income_range,
                "occupation":                   occupation,
                "savings_mindset":              profile.get("savings_mindset"),
                "risk_tolerance_bucket":        _int_bucket(profile.get("risk_tolerance")),
                "financial_volatility_bucket":  _int_bucket(profile.get("financial_volatility")),
                "goal_orientation":             profile.get("goal_orientation"),
                "stress_baseline_bucket":       _int_bucket(profile.get("stress_baseline")),
                "motivation_primary":           profile.get("motivation_primary"),
                "emotional_volatility_bucket":  _int_bucket(profile.get("emotional_volatility")),
                "observed_period":              period,
                "jitter_offset_days":           random.randint(-jitter_days, jitter_days),
                "batch_id":                     batch_id,
                "inserted_at":                  datetime.now(UTC).isoformat(),
            })

    if snapshots:
        aria_client = get_aria_client()
        aria_client.schema("aria").from_("user_profile_snapshots").insert(snapshots).execute()
        inserted = len(snapshots)

    logger.info(
        "snapshot_profiles_completed",
        total=len(rows),
        inserted=inserted,
        skipped_buckets=skipped_buckets,
        period=period,
        batch_id=batch_id,
    )
    return {
        "total":           len(rows),
        "inserted":        inserted,
        "skipped_buckets": skipped_buckets,
        "period":          period,
        "batch_id":        batch_id,
    }
