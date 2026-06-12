"""
tests/unit/test_browser_pool_channel.py — Selección de canal del BrowserPool.

Sprint ingesta 2026-06-12 (Fase A3/A4): en prod el pool caía silenciosamente
a Chromium bundled (sin Chrome real instalado) y bundled headless tecleaba
mal el '$' de la clave. Estos tests pinean:

    1. Default: se intenta Chrome real primero (channel="chrome").
    2. Si Chrome no está, fallback a bundled (sin channel kwarg).
    3. channel="bundled" fuerza bundled sin intentar Chrome — el modo repro
       de --force-bundled en scripts/test_bchile_scraper.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from sky.ingestion import browser_pool as browser_pool_module
from sky.ingestion.browser_pool import BrowserPool


class FakeBrowser:
    async def close(self) -> None:
        pass


class FakeChromium:
    def __init__(self, fail_chrome: bool = False):
        self.launch_calls: list[dict[str, Any]] = []
        self._fail_chrome = fail_chrome

    async def launch(self, **kwargs: Any) -> FakeBrowser:
        self.launch_calls.append(kwargs)
        if self._fail_chrome and kwargs.get("channel") == "chrome":
            raise RuntimeError("chrome no instalado")
        return FakeBrowser()


class FakePlaywright:
    def __init__(self, fail_chrome: bool = False):
        self.chromium = FakeChromium(fail_chrome)

    async def stop(self) -> None:
        pass


def _patch_playwright(monkeypatch: pytest.MonkeyPatch, fake: FakePlaywright) -> None:
    class _Starter:
        async def start(self) -> FakePlaywright:
            return fake

    monkeypatch.setattr(browser_pool_module, "async_playwright", lambda: _Starter())


async def test_default_intenta_chrome_real_primero(monkeypatch):
    fake = FakePlaywright()
    _patch_playwright(monkeypatch, fake)

    pool = BrowserPool(pool_size=1)
    await pool.start()

    assert len(fake.chromium.launch_calls) == 1
    assert fake.chromium.launch_calls[0].get("channel") == "chrome"
    await pool.stop()


async def test_fallback_a_bundled_si_chrome_no_esta(monkeypatch):
    fake = FakePlaywright(fail_chrome=True)
    _patch_playwright(monkeypatch, fake)

    pool = BrowserPool(pool_size=1)
    await pool.start()

    assert len(fake.chromium.launch_calls) == 2
    assert fake.chromium.launch_calls[0].get("channel") == "chrome"
    assert "channel" not in fake.chromium.launch_calls[1]
    await pool.stop()


async def test_channel_bundled_fuerza_bundled_sin_intentar_chrome(monkeypatch):
    """Modo repro local del bug '$': exactamente el Chromium que usa prod."""
    fake = FakePlaywright()
    _patch_playwright(monkeypatch, fake)

    pool = BrowserPool(pool_size=1, channel="bundled")
    await pool.start()

    assert len(fake.chromium.launch_calls) == 1
    assert "channel" not in fake.chromium.launch_calls[0]
    # En modo repro no se respeta chrome_path: bundled de verdad.
    assert "executable_path" not in fake.chromium.launch_calls[0]
    await pool.stop()
