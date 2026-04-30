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

SUPPORTED_BANKS = [
    {"id": "bchile",      "name": "Banco de Chile",  "icon": "🏦", "status": "active",  "has_2fa": True},   # noqa: E501
    {"id": "falabella",   "name": "Banco Falabella", "icon": "🏦", "status": "active",  "has_2fa": False},  # noqa: E501
    {"id": "bci",         "name": "BCI",             "icon": "🏦", "status": "pending", "has_2fa": True},   # noqa: E501
    {"id": "santander",   "name": "Santander Chile", "icon": "🏦", "status": "pending", "has_2fa": True},   # noqa: E501
    {"id": "bancoestado", "name": "Banco Estado",    "icon": "🏦", "status": "pending", "has_2fa": True},   # noqa: E501
    {"id": "itau",        "name": "Itaú Chile",      "icon": "🏦", "status": "pending", "has_2fa": False},  # noqa: E501
    {"id": "scotiabank",  "name": "Scotiabank Chile","icon": "🏦", "status": "pending", "has_2fa": False},  # noqa: E501
    {"id": "mercadopago", "name": "Mercado Pago",    "icon": "💳", "status": "pending", "has_2fa": False},  # noqa: E501
]


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
        from sky.ingestion.sources.bci_direct import BCIDirectSource
        from sky.ingestion.sources.falabella_scraper import FalabellaScraperSource

        for src in (
            BChileScraperSource(),
            FalabellaScraperSource(),
            BCIDirectSource(),
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
