"""
sky.ingestion.routing.rules — Carga reglas de routing desde DB.

Lee de public.ingestion_routing_rules (migración 001). Cachea en memoria
con TTL corto para no consultar DB en cada ingest. Si la DB no responde
y routing_rules_db_required=False, cae a DEFAULT_RULES.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.ingestion.routing.router import RoutingRule

logger = get_logger("routing_rules")


# Bootstrap fallback. Mantener sincronizado con SUPPORTED_BANKS.
DEFAULT_RULES: list[RoutingRule] = [
    RoutingRule(bank_id="bchile",      source_chain=["scraper.bchile"]),
    RoutingRule(bank_id="falabella",   source_chain=["scraper.falabella"]),
    RoutingRule(bank_id="bci",         source_chain=["scraper.bci"]),
    RoutingRule(bank_id="santander",   source_chain=["scraper.santander"]),
    RoutingRule(bank_id="bancoestado", source_chain=["scraper.bancoestado"]),
    RoutingRule(bank_id="itau",        source_chain=["scraper.itau"]),
    RoutingRule(bank_id="scotiabank",  source_chain=["scraper.scotiabank"]),
    RoutingRule(bank_id="mercadopago", source_chain=["mercadopago.api"]),
]


@dataclass
class _Cache:
    rules: list[RoutingRule]
    loaded_at: float


_cache: _Cache | None = None


_SELECT_SQL = text("""
    SELECT bank_id, source_chain, rollout_pct, user_cohort
      FROM public.ingestion_routing_rules
     WHERE enabled = true
""")


async def load_rules_from_db(*, force: bool = False) -> list[RoutingRule]:
    """
    Lee reglas activas desde DB, con cache TTL.

    Args:
        force: bypass cache. Útil para tests y para un endpoint admin futuro.

    Si la DB falla:
        - routing_rules_db_required=True   → relanza la excepción.
        - routing_rules_db_required=False  → log warning + DEFAULT_RULES.
    """
    global _cache
    now = time.time()

    if (
        not force
        and _cache is not None
        and (now - _cache.loaded_at) < settings.routing_rules_cache_ttl_sec
    ):
        return _cache.rules

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(_SELECT_SQL)
            rows = result.fetchall()
    except Exception as exc:
        if settings.routing_rules_db_required:
            logger.error("routing_rules_db_failed", error=str(exc))
            raise
        logger.warning("routing_rules_db_failed_fallback", error=str(exc))
        _cache = _Cache(rules=DEFAULT_RULES, loaded_at=now)
        return DEFAULT_RULES

    rules = [
        RoutingRule(
            bank_id=row.bank_id,
            source_chain=list(row.source_chain),
            rollout_percentage=row.rollout_pct,
            user_cohort=row.user_cohort,
        )
        for row in rows
    ]

    if not rules:
        logger.warning("routing_rules_empty_using_defaults")
        rules = DEFAULT_RULES

    _cache = _Cache(rules=rules, loaded_at=now)
    logger.info("routing_rules_loaded", count=len(rules))
    return rules


def invalidate_cache() -> None:
    """Forzar recarga en próximo load_rules_from_db(). Para admin/tests."""
    global _cache
    _cache = None
