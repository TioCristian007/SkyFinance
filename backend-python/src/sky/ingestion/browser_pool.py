"""
sky.ingestion.browser_pool — Pool reutilizable de browsers Playwright.

El pool mantiene N browsers abiertos (default 4). Cada scrape adquiere
un contexto nuevo — sesión limpia sin compartir cookies — y lo devuelve
al terminar. El browser no se cierra, se reutiliza.

Beneficios vs abrir/cerrar Chromium en cada sync:
    - Cold start de 2-3s → ~0s
    - Memoria estable (no fragmentación por create/destroy)
    - Paralelismo controlado sin OOM
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from sky.core.config import settings
from sky.core.logging import get_logger

logger = get_logger("browser_pool")


class BrowserPool:
    def __init__(self, pool_size: int | None = None, headless: bool = True):
        self._pool_size = pool_size or settings.browser_pool_size
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(self._pool_size)
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._playwright = await async_playwright().start()

        launch_kwargs: dict = {
            "headless": self._headless,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
            ],
        }
        # Solo pasar executable_path si está configurado Y el archivo existe.
        # Si no, Playwright usa su propio Chromium (instalado con `playwright install`).
        if settings.chrome_path and os.path.exists(settings.chrome_path):
            launch_kwargs["executable_path"] = settings.chrome_path

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._started = True
        logger.info("browser_pool_started", pool_size=self._pool_size, headless=self._headless)

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._started = False
        logger.info("browser_pool_stopped")

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[BrowserContext, None]:
        """
        Adquiere un contexto de browser limpio del pool.
        Bloquea si todos los slots están en uso (semáforo).
        El contexto se destruye al salir — el browser se reutiliza.
        """
        if not self._started or not self._browser:
            raise RuntimeError("BrowserPool no ha sido iniciado. Llamar start() primero.")

        async with self._semaphore:
            context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                locale="es-CL",
                timezone_id="America/Santiago",
            )
            try:
                yield context
            finally:
                await context.close()


# Singleton global — se inicia en el lifespan del worker
_pool: BrowserPool | None = None


def get_browser_pool() -> BrowserPool:
    global _pool
    if _pool is None:
        _pool = BrowserPool()
    return _pool

def set_browser_pool(pool: BrowserPool) -> None:
    """Permite inyectar un pool personalizado (útil para tests)."""
    global _pool
    _pool = pool
