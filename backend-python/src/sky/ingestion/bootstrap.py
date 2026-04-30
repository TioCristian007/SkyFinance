"""
sky.ingestion.bootstrap — Construcción única del IngestionRouter.

Llamado desde:
    - api.main:lifespan       → include_browser_sources=False
    - worker.main:startup     → include_browser_sources=True

El router se guarda en app.state.router (API) o ctx["router"] (worker).
"""

from __future__ import annotations

from redis.asyncio import Redis

from sky.core.config import settings
from sky.core.logging import get_logger
from sky.ingestion.rate_limiter import RateLimiter
from sky.ingestion.routing.router import IngestionRouter
from sky.ingestion.routing.rules import load_rules_from_db
from sky.ingestion.sources import build_all_sources

logger = get_logger("bootstrap")


async def build_router(
    *, include_browser_sources: bool
) -> tuple[IngestionRouter, Redis]:
    """
    Devuelve (router, redis_client). El caller es responsable de cerrar el
    cliente Redis en shutdown.

    Falla rápido si Redis no responde.
    """
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    await redis.ping()

    sources = build_all_sources(include_browser_sources=include_browser_sources)
    rules = await load_rules_from_db()
    rate_limiter = RateLimiter.from_settings(redis)

    router = IngestionRouter(
        sources=sources,
        redis=redis,
        rules=rules,
        rate_limiter=rate_limiter,
    )
    logger.info(
        "router_built",
        sources=len(sources),
        rules=len(rules),
        with_browser=include_browser_sources,
    )
    return router, redis
