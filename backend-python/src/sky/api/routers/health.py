"""sky.api.routers.health — Health check endpoints."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine

router = APIRouter(tags=["health"])


async def check_db() -> str:
    """SELECT 1 con timeout 2s. Retorna 'ok' | 'down'."""
    try:
        async with asyncio.timeout(2.0):
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "down"


async def check_redis(redis: Any) -> str:
    """PING con timeout 1s. Retorna 'ok' | 'down'."""
    try:
        async with asyncio.timeout(1.0):
            await redis.ping()
        return "ok"
    except Exception:
        return "down"


def check_anthropic() -> str:
    """Verifica key format. NO llama a la API. Retorna 'ok' | 'missing'."""
    key = settings.anthropic_api_key
    return "ok" if key and key.startswith("sk-ant-") else "missing"


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": "sky-backend-python"}


@router.get("/api/health/deep")
async def health_deep(request: Request) -> JSONResponse:
    db = await check_db()
    redis = await check_redis(request.app.state.redis)
    anth = check_anthropic()

    is_core_ok = db == "ok" and redis == "ok"
    if is_core_ok and anth == "ok":
        status = "ok"
    elif is_core_ok:
        status = "degraded"
    else:
        status = "down"
    http_status = 200 if is_core_ok else 503

    return JSONResponse(
        status_code=http_status,
        content={"status": status, "db": db, "redis": redis, "anthropic": anth},
    )
