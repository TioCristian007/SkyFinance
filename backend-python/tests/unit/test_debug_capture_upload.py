"""
tests/unit/test_debug_capture_upload.py — Capturas debug durables (C3, sprint 2026-06-12).

Con scraper_debug_bucket configurado, _capture_debug sube screenshot + HTML
a Supabase Storage además del filesystem local (que en el contenedor es
efímero). Sin bucket, el comportamiento local queda intacto.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sky.core.config import settings
from sky.ingestion.sources.bchile_scraper import BChileScraperSource


class FakeCapturePage:
    async def screenshot(self, path: str) -> None:
        Path(path).write_bytes(b"fake-png")

    async def content(self) -> str:
        return "<html>captura de prueba</html>"


class FakeStorageBucket:
    def __init__(self, uploads: list):
        self._uploads = uploads

    def upload(self, key: str, data: bytes, opts: dict) -> None:
        self._uploads.append((key, len(data), opts.get("content-type")))


class FakeClient:
    def __init__(self, uploads: list):
        self._uploads = uploads
        self.buckets_pedidos: list[str] = []

    @property
    def storage(self):
        outer = self

        class _Storage:
            def from_(self, bucket: str) -> FakeStorageBucket:
                outer.buckets_pedidos.append(bucket)
                return FakeStorageBucket(outer._uploads)

        return _Storage()


@pytest.fixture
def debug_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "scraper_debug_capture", True)
    monkeypatch.setattr(settings, "scraper_debug_dir", str(tmp_path))
    return tmp_path


async def test_capture_sube_png_y_html_al_bucket(debug_settings, monkeypatch):
    monkeypatch.setattr(settings, "scraper_debug_bucket", "scraper-debug")
    uploads: list = []
    fake_client = FakeClient(uploads)
    monkeypatch.setattr("sky.core.db.get_service_client", lambda: fake_client)

    scraper = BChileScraperSource()
    await scraper._capture_debug(FakeCapturePage(), "test_label")

    assert len(uploads) == 2
    keys = [k for k, _, _ in uploads]
    assert any(k.startswith("bchile/") and k.endswith(".png") for k in keys)
    assert any(k.startswith("bchile/") and k.endswith(".html") for k in keys)
    assert fake_client.buckets_pedidos == ["scraper-debug", "scraper-debug"]
    # Los archivos locales también quedan (comportamiento original intacto)
    assert list(debug_settings.glob("bchile_test_label_*.png"))


async def test_sin_bucket_no_intenta_subir(debug_settings, monkeypatch):
    monkeypatch.setattr(settings, "scraper_debug_bucket", "")

    def _boom():
        raise AssertionError("no debería pedir el cliente sin bucket configurado")

    monkeypatch.setattr("sky.core.db.get_service_client", _boom)

    scraper = BChileScraperSource()
    await scraper._capture_debug(FakeCapturePage(), "solo_local")

    assert list(debug_settings.glob("bchile_solo_local_*.html"))


async def test_fallo_de_upload_no_propaga(debug_settings, monkeypatch):
    """El upload es best-effort: un fallo de storage jamás rompe el flujo
    del scraper (que ya está manejando un error real del banco)."""
    monkeypatch.setattr(settings, "scraper_debug_bucket", "scraper-debug")

    class BrokenClient:
        @property
        def storage(self):
            raise RuntimeError("storage caído")

    monkeypatch.setattr("sky.core.db.get_service_client", lambda: BrokenClient())

    scraper = BChileScraperSource()
    await scraper._capture_debug(FakeCapturePage(), "upload_roto")  # no lanza
