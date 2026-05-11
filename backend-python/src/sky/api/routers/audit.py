"""sky.api.routers.audit — GET /api/audit/me (lectura propia del audit log)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

from sky.api.deps import require_user_id
from sky.api.middleware.rate_limit import limiter
from sky.api.schemas.audit import AuditEventListResponse, AuditEventOut
from sky.core.audit import _ACTION_MAP, _hash
from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("audit_router")
router = APIRouter(prefix="/api/audit", tags=["audit"])

# Valores de event_type conocidos (primeras partes de los tuples en _ACTION_MAP).
# Importamos _ACTION_MAP en lugar de duplicar la lógica de hashing — misma fuente de verdad.
_KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    event_type for event_type, _ in _ACTION_MAP.values()
)


@router.get("/me", response_model=AuditEventListResponse)
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")  # type: ignore[untyped-decorator]
async def get_audit_me(
    request: Request,
    user_id: str = Depends(require_user_id),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None),
) -> AuditEventListResponse:
    """
    Retorna el historial de eventos de auditoría del usuario autenticado.

    Seguridad:
    - user_hash calculado en backend con SHA-256(user_id + salt) — nunca expuesto al cliente.
    - Filtro user_hash es exact match (no LIKE) — sin posibilidad de cross-user leakage.
    - Parámetros son bind params — sin SQL injection.
    - event_type desconocido devuelve lista vacía (no revela estructura interna del mapa).
    """
    if event_type is not None and event_type not in _KNOWN_EVENT_TYPES:
        return AuditEventListResponse(events=[], total=0, limit=limit, offset=offset)

    user_hash = _hash(user_id)

    count_sql = "SELECT COUNT(*) FROM public.audit_log WHERE user_hash = :hash"
    data_sql = (
        "SELECT event_type, outcome, resource_type, resource_id, detail, occurred_at "
        "FROM public.audit_log WHERE user_hash = :hash"
    )
    params: dict[str, Any] = {"hash": user_hash}
    if event_type is not None:
        count_sql += " AND event_type = :event_type"
        data_sql += " AND event_type = :event_type"
        params["event_type"] = event_type

    data_sql += " ORDER BY occurred_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    engine = get_engine()
    async with engine.connect() as conn:
        total_result = await conn.execute(text(count_sql), params)
        total = total_result.scalar() or 0

        data_result = await conn.execute(text(data_sql), params)
        rows = data_result.fetchall()

    events = [
        AuditEventOut(
            event_type=row[0],
            outcome=row[1],
            resource_type=row[2],
            resource_id=str(row[3]) if row[3] else None,
            detail=row[4] if row[4] else {},
            occurred_at=row[5],
        )
        for row in rows
    ]

    return AuditEventListResponse(events=events, total=total, limit=limit, offset=offset)
