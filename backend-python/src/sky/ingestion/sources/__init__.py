"""
sky.ingestion.sources — Registry de DataSources.

Fase 4: agregar BChileScraperSource, FalabellaScraperSource
Fase 5+: agregar FintocSource, BCIDirectSource, etc.
"""
from sky.ingestion.contracts import DataSource

_SOURCES: dict[str, DataSource] = {}

def register_source(source: DataSource) -> None:
    _SOURCES[source.source_identifier] = source

def get_all_sources() -> dict[str, DataSource]:
    return dict(_SOURCES)

def get_source(source_id: str) -> DataSource | None:
    return _SOURCES.get(source_id)

SUPPORTED_BANKS = [
    {"id": "bchile",      "name": "Banco de Chile",  "icon": "🏦", "status": "active",  "has_2fa": True},
    {"id": "falabella",   "name": "Banco Falabella",  "icon": "🏦", "status": "active",  "has_2fa": False},
    {"id": "bci",         "name": "BCI",              "icon": "🏦", "status": "pending", "has_2fa": True},
    {"id": "santander",   "name": "Santander Chile",  "icon": "🏦", "status": "pending", "has_2fa": True},
    {"id": "bancoestado", "name": "Banco Estado",     "icon": "🏦", "status": "pending", "has_2fa": True},
    {"id": "itau",        "name": "Itaú Chile",       "icon": "🏦", "status": "pending", "has_2fa": False},
    {"id": "scotiabank",  "name": "Scotiabank Chile", "icon": "🏦", "status": "pending", "has_2fa": False},
    {"id": "mercadopago", "name": "Mercado Pago",     "icon": "💳", "status": "pending", "has_2fa": False},
]
