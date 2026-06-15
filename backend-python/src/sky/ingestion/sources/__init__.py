"""
sky.ingestion.sources — Factory de DataSources.

build_all_sources() construye TODAS las sources concretas con sus
dependencias. Se llama una vez por proceso desde el bootstrap
(api.main:lifespan o worker.main:startup).

CONTRATO:
    - Cada source que retorna build_all_sources() debe responder a su
      source_identifier declarado en contracts.
    - Si una source requiere browser, sólo se incluye si el caller
      pasa include_browser_sources=True (la API NUNCA debe).
"""

from __future__ import annotations

from sky.core.logging import get_logger
from sky.ingestion.contracts import DataSource

logger = get_logger("sources_factory")

SUPPORTED_BANKS: list[dict[str, object]] = [
    {
        "id": "bchile", "name": "Banco de Chile", "icon": "🏦",
        "status": "active", "has_2fa": True, "account_type": "Cta. Corriente",
    },
    {
        "id": "bci", "name": "BCI", "icon": "🏦",
        "status": "active", "has_2fa": True, "account_type": "Cta. Vista",
    },
]


def account_type_for(bank_id: str) -> str:
    """Tipo de cuenta por banco; fallback 'Cuenta' para ids desconocidos."""
    for bank in SUPPORTED_BANKS:
        if bank["id"] == bank_id:
            return str(bank["account_type"])
    return "Cuenta"


def build_all_sources(*, include_browser_sources: bool) -> dict[str, DataSource]:
    """
    Construye el dict {source_identifier: instance}.

    include_browser_sources=False  → solo sources sin Playwright (API).
    include_browser_sources=True   → también scrapers (Worker).
    """
    sources: dict[str, DataSource] = {}

    if include_browser_sources:
        # Importar dentro del bloque para que la API jamás cargue Playwright.
        from sky.ingestion.sources.bchile_scraper import BChileScraperSource
        from sky.ingestion.sources.bci_scraper import BCIScraperSource

        # FalabellaScraperSource es un skeleton no implementado y `falabella` no
        # está en SUPPORTED_BANKS (el endpoint de conexión lo rechaza). No se
        # registra para no exponer una fuente muerta. Ver R-3 en 08_ESTADO_Y_DEUDA.
        for src in (
            BChileScraperSource(),
            BCIScraperSource(),
        ):
            sources[src.source_identifier] = src

    # APIs HTTP-only (no requieren browser): Fintoc, MercadoPago, SFA se
    # registran aquí cuando estén listos. Hoy ninguna está implementada.
    # TODO (Fase 6+): registrar FintocSource, MercadoPagoApiSource, SFASource.

    logger.info(
        "sources_built",
        count=len(sources),
        ids=list(sources.keys()),
        with_browser=include_browser_sources,
    )
    return sources
