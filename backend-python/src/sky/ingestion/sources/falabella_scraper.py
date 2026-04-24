"""
sky.ingestion.sources.falabella_scraper — Scraper Banco Falabella (Playwright).

ESTADO: SKELETON. La estructura e interfaz están correctas y compilan.
La lógica interna de scraping debe completarse por el equipo siguiendo
el código de referencia en backend/node_modules/open-banking-chile/dist/index.js
líneas 2738-3100 (scrapeFalabella).

DIFERENCIAS CON BCHILE:
    - No hay APIs REST internas → scraping directo de DOM + Shadow DOM
    - Shadow DOM: <credit-card-movements> contiene la tabla CMR
    - Sin 2FA (por ahora — puede cambiar)
    - Los movimientos CMR están en dos tabs: "últimos" e "invoiced"

PASOS A IMPLEMENTAR:
    1. _login: fill RUT + password, submit, esperar dashboard
    2. _extract_cupos: montos de cupo CMR desde innerText (regex)
    3. _navigate_to_movements: click en "cartola" / "movimientos"
    4. _extract_cmr_movements: query dentro del Shadow DOM de credit-card-movements
    5. _paginate: click en .btn-pagination hasta que desaparezca

Para datos de test, correr con una cuenta real y comparar contra el
scraper Node actual — mismo banco, mismo usuario, mismos movimientos.
"""

from __future__ import annotations

from datetime import date, datetime

from sky.core.logging import get_logger
from sky.ingestion.browser_pool import get_browser_pool
from sky.ingestion.contracts import (
    BankCredentials,
    CanonicalMovement,
    DataSource,
    IngestionCapabilities,
    IngestionResult,
    MovementSource,
    OAuthTokens,
    ProgressCallback,
    RecoverableIngestionError,
    SourceKind,
)

logger = get_logger("falabella_scraper")

BANK_URL = "https://www.bancofalabella.cl"
SHADOW_HOST = "credit-card-movements"


class FalabellaScraperSource(DataSource):
    """DataSource para Banco Falabella. TODO: completar lógica de scraping."""

    @property
    def source_identifier(self) -> str:
        return "scraper.falabella"

    @property
    def source_kind(self) -> SourceKind:
        return SourceKind.SCRAPER

    @property
    def supported_banks(self) -> list[str]:
        return ["falabella"]

    def capabilities(self) -> IngestionCapabilities:
        return IngestionCapabilities(
            typical_latency_ms=90_000,
            estimated_failure_rate=0.20,
            supports_backfill=True,
            backfill_days=60,
            provides_credit_card=True,
            provides_movements=True,
        )

    async def fetch(
        self,
        bank_id: str,
        credentials: BankCredentials | OAuthTokens,
        *,
        on_progress: ProgressCallback | None = None,
        since: date | None = None,
    ) -> IngestionResult:
        if not isinstance(credentials, BankCredentials):
            raise ValueError("Falabella requiere BankCredentials")

        progress = on_progress or (lambda s: None)
        started_at = datetime.now()
        pool = get_browser_pool()

        async with pool.acquire() as context:
            page = await context.new_page()

            try:
                progress("Abriendo Banco Falabella...")
                await page.goto(BANK_URL, wait_until="networkidle", timeout=45_000)

                # TODO(equipo): portar scrapeFalabella() de open-banking-chile
                #   1. _login(page, rut, password)
                #   2. _extract_cupos(page) → balance
                #   3. _navigate_to_movements(page)
                #   4. _extract_cmr_movements(page, since) → list[CanonicalMovement]
                #   5. _paginate hasta fin o hasta fecha < since
                raise RecoverableIngestionError(
                    "FalabellaScraperSource no implementado aún. "
                    "Ver docstring para pasos."
                )

            except Exception as exc:
                logger.error("falabella_fetch_failed", error=str(exc))
                raise

        # Cuando esté implementado, devolver:
        # return IngestionResult(
        #     balance=AccountBalance(balance_clp=cupo_disponible, as_of=datetime.now()),
        #     movements=movements,
        #     source_kind=SourceKind.SCRAPER,
        #     source_identifier=self.source_identifier,
        #     elapsed_ms=int((datetime.now() - started_at).total_seconds() * 1000),
        # )
