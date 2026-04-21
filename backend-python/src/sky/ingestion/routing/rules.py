"""
sky.ingestion.routing.rules — Lee reglas desde ingestion_routing_rules.

TODO (Fase 5): implementar lectura de DB.
"""
from __future__ import annotations
from sky.ingestion.routing.router import RoutingRule

# Reglas hardcoded para Fase 4 (antes de tener la tabla SQL).
# En Fase 5 se reemplazan por lectura de DB.
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

async def load_rules_from_db() -> list[RoutingRule]:
    """TODO (Fase 5): leer desde ingestion_routing_rules."""
    return DEFAULT_RULES
