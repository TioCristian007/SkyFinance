"""
tests/integration/test_fill_bundled_chromium.py — fill() preserva '$' en bundled real.

Lanza el Chromium bundled de Playwright (el mismo binario que usa el worker
cuando no hay Chrome real) contra una página local y verifica que fill()
deja el valor EXACTO en un input password, incluyendo el '$' final que
type() manglaba en prod (causa raíz del sprint 2026-06-12).

No toca al banco ni a la red. Se salta si el browser no está instalado
(`playwright install chromium`).
"""

from __future__ import annotations

import pytest

PAGE_HTML = "data:text/html,<input id='clave' type='password'>"
VALOR_CON_DOLAR = "Abc_123$"


async def test_fill_preserva_dolar_en_chromium_bundled():
    try:
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
    except Exception as exc:  # pragma: no cover - depende del entorno
        pytest.skip(f"Playwright no disponible: {exc}")

    try:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - depende del entorno
            pytest.skip(f"Chromium bundled no instalado: {exc}")

        page = await browser.new_page()
        await page.goto(PAGE_HTML)
        await page.fill("#clave", VALOR_CON_DOLAR)
        value = await page.evaluate("() => document.querySelector('#clave').value")
        await browser.close()

        assert value == VALOR_CON_DOLAR
    finally:
        await pw.stop()
