"""sky.api.middleware.idempotency — Deduplicación 24h vía Redis."""
from __future__ import annotations

import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sky.core.config import settings
from sky.core.logging import get_logger

logger = get_logger("idempotency")

# Rutas POST donde aplica la deduplicación
_IDEMPOTENT_PATHS = frozenset({
    "/api/banking/sync",
    "/api/banking/sync-all",
    "/api/banking/accounts",
})

# TTL del sentinel in-progress (seguridad ante crash del proceso)
_INPROGRESS_TTL_SECONDS = 30


def _is_idempotent_route(request: Request) -> bool:
    if request.method != "POST":
        return False
    path = request.url.path
    return any(path == p or path.startswith(p + "/") for p in _IDEMPOTENT_PATHS)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Si el request incluye header 'Idempotency-Key' y la ruta es idempotente:

    1. Cached response en Redis → devuelve inmediato (X-Idempotency-Replay: true).
    2. In-progress (otra instancia procesando la misma key) → 409 + Retry-After: 5.
    3. Sin cache: set sentinel 'inprogress', procesa, cache respuesta 2xx, delete sentinel.

    El sentinel in-progress tiene TTL de 30s para protección ante crashes.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        idk = request.headers.get("Idempotency-Key")
        if not idk or not _is_idempotent_route(request):
            return await call_next(request)

        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return await call_next(request)

        cache_key = f"idk:{idk}"
        inprogress_key = f"idk:inprogress:{idk}"

        try:
            cached = await redis.get(cache_key)
            if cached:
                data: dict[str, Any] = json.loads(cached)
                logger.info("idempotency_replay", key=idk[:8])
                return JSONResponse(
                    status_code=data["status_code"],
                    content=data["content"],
                    headers={"X-Idempotency-Replay": "true"},
                )

            in_progress = await redis.get(inprogress_key)
            if in_progress:
                logger.info("idempotency_in_progress", key=idk[:8])
                return JSONResponse(
                    status_code=409,
                    content={"error": "Request en progreso. Reintenta en unos segundos."},
                    headers={"Retry-After": "5"},
                )

            await redis.setex(inprogress_key, _INPROGRESS_TTL_SECONDS, b"1")
        except Exception as exc:
            logger.warning("idempotency_check_failed", error=str(exc))
            return await call_next(request)

        try:
            response: Response = await call_next(request)

            if 200 <= response.status_code < 300:
                try:
                    body = b""
                    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                        body += chunk if isinstance(chunk, bytes) else chunk.encode()

                    await redis.setex(
                        cache_key,
                        settings.idempotency_ttl_seconds,
                        json.dumps({
                            "status_code": response.status_code,
                            "content": json.loads(body) if body else {},
                        }),
                    )

                    return Response(
                        content=body,
                        status_code=response.status_code,
                        media_type=response.media_type,
                        headers=dict(response.headers),
                    )
                except Exception as exc:
                    logger.warning("idempotency_cache_write_failed", error=str(exc))

            return response
        finally:
            with contextlib.suppress(Exception):
                await redis.delete(inprogress_key)
