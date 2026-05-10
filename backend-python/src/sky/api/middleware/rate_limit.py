"""sky.api.middleware.rate_limit — slowapi Limiter Redis-backed (Fase 11 — P2-3)."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from sky.core.config import settings


def _get_rate_limit_key(request: Request) -> str:
    """
    Rate limit key: user_id verificado (seteado por JWTContextMiddleware).
    IP como fallback para endpoints públicos o requests sin JWT válido.

    JWTContextMiddleware DEBE correr antes de SlowAPIMiddleware para que
    request.state.user_id esté disponible aquí. Ver LIFO en main.py.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


# Redis-backed: contador compartido entre todas las instancias del API.
# Garantía de autoescala — si se agregan instancias en Railway, el límite
# sigue siendo efectivo a nivel global (no por proceso).
limiter = Limiter(
    key_func=_get_rate_limit_key,
    storage_uri=settings.redis_url,
)


def on_rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:  # noqa: ARG001
    return JSONResponse(
        status_code=429,
        content={"error": "Rate limit excedido. Intenta en unos segundos."},
    )
