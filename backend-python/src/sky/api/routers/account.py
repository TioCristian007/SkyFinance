"""sky.api.routers.account — Customer data export endpoints (Ley 19.628 art 11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from sky.api.deps import require_user_id
from sky.api.middleware.rate_limit import limiter
from sky.api.schemas.account import DataExportRequestCreate, DataExportRequestOut
from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.errors import NotFoundError
from sky.core.logging import get_logger

logger = get_logger("account_router")
router = APIRouter(prefix="/api/account", tags=["account"])


@router.post("/export-request", response_model=DataExportRequestOut, status_code=201)
@limiter.limit("5/minute")  # type: ignore[untyped-decorator]
async def create_export_request(
    body: DataExportRequestCreate,
    request: Request,
    user_id: str = Depends(require_user_id),
) -> DataExportRequestOut:
    """
    Crea solicitud de exportación de datos del usuario (Ley 19.628 art 11).

    Encola process_export_request_job en el worker. El job genera el ZIP y
    actualiza status a 'completed' con signed URL de 7 días, o 'failed' si hay error.
    Rate limit: 5/min — más restrictivo que el default para prevenir abuso.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                INSERT INTO public.data_export_requests (user_id, format, expires_at)
                VALUES (:user_id, :format, NOW() + INTERVAL '7 days')
                RETURNING id, user_id, status, format, download_url,
                          expires_at, requested_at, delivered_at
            """),
            {"user_id": user_id, "format": body.format},
        )
        row = result.fetchone()

    arq_pool = request.app.state.arq_pool
    await arq_pool.enqueue_job("process_export_request_job", str(row[0]))
    logger.info("export_request_created", request_id=str(row[0]), format=body.format)

    return DataExportRequestOut(
        id=str(row[0]),
        status=row[2],
        format=row[3],
        download_url=row[4],
        expires_at=row[5],
        requested_at=row[6],
        delivered_at=row[7],
    )


@router.get("/export-request", response_model=list[DataExportRequestOut])
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")  # type: ignore[untyped-decorator]
async def list_export_requests(
    request: Request,
    user_id: str = Depends(require_user_id),
) -> list[DataExportRequestOut]:
    """Lista los últimos 10 export requests del usuario autenticado."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, user_id, status, format, download_url,
                       expires_at, requested_at, delivered_at
                FROM public.data_export_requests
                WHERE user_id = :user_id
                ORDER BY requested_at DESC LIMIT 10
            """),
            {"user_id": user_id},
        )
        rows = result.fetchall()

    return [
        DataExportRequestOut(
            id=str(r[0]),
            status=r[2],
            format=r[3],
            download_url=r[4],
            expires_at=r[5],
            requested_at=r[6],
            delivered_at=r[7],
        )
        for r in rows
    ]


@router.get("/export-request/{request_id}", response_model=DataExportRequestOut)
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")  # type: ignore[untyped-decorator]
async def get_export_request(
    request_id: str,
    request: Request,
    user_id: str = Depends(require_user_id),
) -> DataExportRequestOut:
    """Poll status de un export request específico del usuario autenticado."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, user_id, status, format, download_url,
                       expires_at, requested_at, delivered_at
                FROM public.data_export_requests
                WHERE id = :request_id AND user_id = :user_id
            """),
            {"request_id": request_id, "user_id": user_id},
        )
        row = result.fetchone()

    if not row:
        raise NotFoundError("Export request no encontrado")

    return DataExportRequestOut(
        id=str(row[0]),
        status=row[2],
        format=row[3],
        download_url=row[4],
        expires_at=row[5],
        requested_at=row[6],
        delivered_at=row[7],
    )
