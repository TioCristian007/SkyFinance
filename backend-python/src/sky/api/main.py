"""
sky.api.main — Entry point de la API FastAPI.

Principio: la API NUNCA ejecuta Playwright ni scraping.
Solo encola jobs para el worker vía ARQ.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sky.api.routers import (
    banking,
    challenges,
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
from sky.ingestion.bootstrap import build_router

logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup y shutdown hooks."""
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
    app = FastAPI(
        title="Sky Finance API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    dev_origins = [
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
    ]
    allowed = dev_origins + settings.cors_origins_list

    if settings.is_production and not settings.cors_origins_list:
        raise RuntimeError(
            "CORS_ORIGINS debe estar configurado en producción. "
            "No se permite fallback permisivo."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "x-cron-secret"],
    )

    # ── Exception handlers ────────────────────────────────────────────────
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

    # ── Routes ────────────────────────────────────────────────────────────
    app.include_router(banking.router)
    app.include_router(transactions.router)
    app.include_router(summary.router)
    app.include_router(goals.router)
    app.include_router(challenges.router)
    app.include_router(simulate.router)
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

    return app


app = create_app()
