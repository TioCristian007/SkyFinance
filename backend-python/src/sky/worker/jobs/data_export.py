"""sky.worker.jobs.data_export — Genera ZIP con datos del usuario (Ley 19.628 art 11).

max_tries=1: ARQ no auto-retry. Si falla, el usuario re-solicita via POST
/api/account/export-request. Un fallo de export no es crítico para el hot path
y cada intento genera un nuevo registro en data_export_requests.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import uuid
import zipfile
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text

from sky.core.audit import _hash, log_event
from sky.core.db import get_aria_client, get_engine
from sky.core.logging import get_logger

logger = get_logger("data_export")

BUCKET = "data-exports"


async def process_export_request_job(ctx: dict[str, Any], request_id: str) -> dict[str, Any]:
    """
    Genera ZIP con datos del usuario y sube a Supabase Storage.

    Flujo:
    1. Lee request de data_export_requests (user_id, format).
    2. Recopila datos: transactions, goals, challenge_states, earned_badges, audit_log.
    3. Genera ZIP (JSON o CSV según format).
    4. Sube al bucket "data-exports" (pre-requisito: bucket creado manualmente).
    5. Actualiza status='completed' con signed URL (TTL=7d) y delivered_at=NOW().
    6. En fallo: status='failed', error sanitizado (solo tipo, sin stack/paths),
       delivered_at queda NULL, nada se sube a Storage.

    Datos EXCLUIDOS explícitamente: bank_accounts (contiene encrypted_rut/pass).
    max_tries=1: sin auto-retry por ARQ.
    """
    engine = get_engine()

    async with engine.connect() as conn:
        req_result = await conn.execute(
            text(
                "SELECT id, user_id, format FROM public.data_export_requests WHERE id = :id"
            ),
            {"id": request_id},
        )
        req = req_result.fetchone()

    if not req:
        logger.error("export_request_not_found", request_id=request_id)
        return {"status": "not_found"}

    user_id = str(req[1])
    export_format = str(req[2])

    try:
        data = await _collect_user_data(engine, user_id)
        zip_bytes = _build_zip(data, export_format)
        size_bytes = len(zip_bytes)

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        file_path = f"{user_id[:8]}/{request_id}_{timestamp}.zip"
        storage_client = get_aria_client()

        await asyncio.to_thread(
            storage_client.storage.from_(BUCKET).upload,
            file_path,
            zip_bytes,
            {"content-type": "application/zip"},
        )
        signed_result = await asyncio.to_thread(
            storage_client.storage.from_(BUCKET).create_signed_url,
            file_path,
            604800,  # 7 días en segundos
        )

        # Handle both dict and object response shapes (supabase-py version variance)
        if isinstance(signed_result, dict):
            download_url = signed_result.get("signedURL") or signed_result.get("signed_url", "")
        else:
            download_url = (
                getattr(signed_result, "signed_url", None)
                or getattr(signed_result, "signedURL", None)
                or ""
            )

        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE public.data_export_requests
                    SET status = 'completed', delivered_at = NOW(), download_url = :url
                    WHERE id = :id
                """),
                {"url": str(download_url), "id": request_id},
            )

        await log_event(
            action="export.completed",
            user_id=user_id,
            resource_type="data_export",
            resource_id=request_id,
            metadata={"format": export_format, "size_bytes": size_bytes},
        )
        logger.info("export_completed", request_id=request_id, size_bytes=size_bytes)
        return {"status": "completed", "size_bytes": size_bytes}

    except Exception as exc:
        # Solo el tipo de excepción — sin stack trace, sin file paths, sin PII.
        error_type = type(exc).__name__
        logger.error("export_failed", request_id=request_id, error=error_type)

        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE public.data_export_requests SET status = 'failed' WHERE id = :id"
                ),
                {"id": request_id},
            )
        # delivered_at queda NULL — no hay ZIP entregado.
        return {"status": "failed", "error": error_type}


async def _collect_user_data(engine: Any, user_id: str) -> dict[str, list[dict[str, Any]]]:
    """Recopila datos del usuario para el ZIP. Excluye bank_accounts explícitamente."""
    user_hash = _hash(user_id)

    async with engine.connect() as conn:
        # transactions — sin encrypted fields (esos están en bank_accounts)
        txn_result = await conn.execute(
            text("""
                SELECT id, amount, category, description, date, created_at,
                       bank_account_id, external_id, source, movement_source,
                       raw_description, categorization_status
                FROM public.transactions
                WHERE user_id = :uid
                ORDER BY date DESC
            """),
            {"uid": user_id},
        )
        transactions = [dict(row._mapping) for row in txn_result.fetchall()]

        goals_result = await conn.execute(
            text("""
                SELECT id, title, target_amount, saved_amount, deadline, icon, type,
                       status, created_at, completed_at
                FROM public.goals
                WHERE user_id = :uid
            """),
            {"uid": user_id},
        )
        goals = [dict(row._mapping) for row in goals_result.fetchall()]

        # La tabla real es challenge_states, no challenges
        cs_result = await conn.execute(
            text("""
                SELECT id, challenge_id, status, started_at, completed_at,
                       points_earned, created_at
                FROM public.challenge_states
                WHERE user_id = :uid
            """),
            {"uid": user_id},
        )
        challenge_states = [dict(row._mapping) for row in cs_result.fetchall()]

        badges_result = await conn.execute(
            text(
                "SELECT id, badge_id, earned_at FROM public.earned_badges WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        earned_badges = [dict(row._mapping) for row in badges_result.fetchall()]

        # audit_log filtrado por user_hash — la tabla no tiene user_id raw
        audit_result = await conn.execute(
            text("""
                SELECT event_type, outcome, resource_type, resource_id, detail, occurred_at
                FROM public.audit_log
                WHERE user_hash = :hash
                ORDER BY occurred_at DESC
            """),
            {"hash": user_hash},
        )
        audit_log = [dict(row._mapping) for row in audit_result.fetchall()]

        # perfil cualitativo privado (Ley 19.628 art 11: el usuario recibe TODOS sus datos)
        profile_result = await conn.execute(
            text("""
                SELECT savings_mindset, savings_mindset_conf,
                       risk_tolerance, risk_tolerance_conf,
                       financial_volatility, financial_volatility_conf,
                       goal_orientation, goal_orientation_conf,
                       stress_baseline, stress_current, emotional_volatility,
                       last_emotion, last_emotion_at,
                       motivation_primary, motivation_primary_conf,
                       recurring_blockers, protective_behaviors,
                       updates_count, first_observed_at, last_updated_at
                FROM public.user_financial_profile
                WHERE user_id = :uid
            """),
            {"uid": user_id},
        )
        profile_row = profile_result.fetchone()
        perfil_cualitativo = [dict(profile_row._mapping)] if profile_row else []

    return {
        "transactions":      _serialize(transactions),
        "goals":             _serialize(goals),
        "challenge_states":  _serialize(challenge_states),
        "earned_badges":     _serialize(earned_badges),
        "audit_log":         _serialize(audit_log),
        "perfil_cualitativo": _serialize(perfil_cualitativo),
    }


def _serialize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convierte uuid/datetime/date a str para serialización JSON/CSV."""

    def _val(v: Any) -> Any:
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    return [{k: _val(v) for k, v in row.items()} for row in rows]


def _build_zip(data: dict[str, list[dict[str, Any]]], export_format: str) -> bytes:
    """Genera ZIP con los datasets en el formato especificado (json o csv)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, rows in data.items():
            if export_format == "csv":
                content = _to_csv(rows).encode("utf-8")
                zf.writestr(f"{name}.csv", content)
            else:
                content = json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode(
                    "utf-8"
                )
                zf.writestr(f"{name}.json", content)
    return buf.getvalue()


def _to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


process_export_request_job.max_tries = 1  # type: ignore[attr-defined]
