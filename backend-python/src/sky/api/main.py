"""
sky.api.main — Entry point de la API FastAPI.

Principio: la API NUNCA ejecuta Playwright ni scraping.
Solo encola jobs para el worker vía ARQ.
"""
from __future__ import annotations

import secrets as _secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import Response as StarletteResponse

from sky.api.middleware.idempotency import IdempotencyMiddleware
from sky.api.middleware.jwt_context import JWTContextMiddleware
from sky.api.middleware.rate_limit import limiter, on_rate_limit_exceeded
from sky.api.middleware.security_headers import SecurityHeadersMiddleware
from sky.api.middleware.tracing import RequestTimingMiddleware
from sky.api.routers import (
    account,
    audit,
    banking,
    challenges,
    chat,
    goals,
    health,
    internal,
    simulate,
    summary,
    transactions,
    webhooks,
)
from sky.core.config import settings
from sky.core.db import close_engine
from sky.core.errors import (
    AuthenticationError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from sky.core.logging import get_logger, setup_logging
from sky.core.sentry_utils import init_sentry
from sky.ingestion.bootstrap import build_router

logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup y shutdown hooks."""
    init_sentry()
    setup_logging(json_output=settings.is_production)
    logger.info("api_starting", port=settings.port)

    router, redis = await build_router(include_browser_sources=False)
    app.state.router = router
    app.state.redis = redis

    # Pool de ARQ para encolar jobs desde routers
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))

    yield

    await app.state.arq_pool.aclose()
    await redis.aclose()
    await close_engine()
    logger.info("api_stopped")


def create_app() -> FastAPI:
    # ── Fail-fast en producción (secrets críticos) ────────────────────────────
    if settings.is_production and not settings.cors_origins_list:
        raise RuntimeError(
            "CORS_ORIGINS debe estar configurado en producción. "
            "No se permite fallback permisivo."
        )
    if settings.is_production and not settings.prometheus_secret:
        raise RuntimeError(
            "PROMETHEUS_SECRET requerido en producción. "
            "Las métricas no pueden ser públicas."
        )
    if settings.is_production and not settings.sentry_dsn:
        raise RuntimeError(
            "SENTRY_DSN requerido en producción. "
            "La falta de Sentry en prod es un agujero de observabilidad."
        )

    app = FastAPI(
        title="Sky Finance API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )

    # ── Rate limiting (slowapi + Redis-backed) ────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, on_rate_limit_exceeded)

    # ── Middleware stack (LIFO: último añadido = más externo en request) ──────
    # Orden de ejecución en request:
    #   CORS → SecurityHeaders → JWTContext → SlowAPI → Idempotency → RequestTiming → handler
    #
    # CORS debe ser el más externo para interceptar OPTIONS antes que nadie.
    # Si cualquier middleware interno corre antes del preflight, CORS falla.
    app.add_middleware(RequestTimingMiddleware)      # 1° añadido = más interno
    app.add_middleware(IdempotencyMiddleware)        # 2°
    app.add_middleware(SlowAPIMiddleware)            # 3° — aplica rate limit (lee user_id de state)
    app.add_middleware(JWTContextMiddleware)         # 4° — setea user_id antes que SlowAPI
    app.add_middleware(SecurityHeadersMiddleware)    # 5°

    dev_origins = [
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
    ]
    allowed = dev_origins + settings.cors_origins_list

    # CORS último = más externo = intercepta OPTIONS antes que nadie
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "x-cron-secret", "Idempotency-Key"],
    )

    # ── Exception handlers ────────────────────────────────────────────────────
    @app.exception_handler(AuthenticationError)
    async def auth_handler(_: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"error": str(exc)})

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(_: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"error": str(exc)})

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(ValidationError)
    async def validation_handler(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(RateLimitError)
    async def rate_limit_handler(_: Request, exc: RateLimitError) -> JSONResponse:
        return JSONResponse(status_code=429, content={"error": str(exc)})

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(audit.router)          # Fase 12: GET /api/audit/me
    app.include_router(account.router)        # Fase 12: /api/account/export-request
    app.include_router(banking.router)
    app.include_router(transactions.router)
    app.include_router(summary.router)
    app.include_router(goals.router)
    app.include_router(challenges.router)
    app.include_router(simulate.router)
    app.include_router(chat.router)
    app.include_router(webhooks.router)
    app.include_router(internal.router)
    app.include_router(health.router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "status": "ok",
            "app": "sky-backend-python",
            "version": "0.1.0",
        }

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> StarletteResponse:
        if settings.prometheus_secret:
            provided = request.headers.get("x-prometheus-secret", "")
            if not _secrets.compare_digest(provided, settings.prometheus_secret):
                return JSONResponse(status_code=401, content={"error": "unauthorized"})
        return StarletteResponse(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return app


app = create_app()