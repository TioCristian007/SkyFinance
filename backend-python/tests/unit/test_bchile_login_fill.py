"""
tests/unit/test_bchile_login_fill.py — Regresión del login BChile (sprint ingesta 2026-06-12).

Causa raíz del bloqueador del MVP: la clave terminada en '$' se manglaba al
teclearse con type() en Chromium bundled headless (prod), mientras que local
con Chrome real funcionaba. Estos tests pinean:

    1. La clave se llena con fill() y preserva '$' (y cualquier char con Shift).
    2. El RUT SIGUE usando type() — la directiva Angular delete-zero-left
       requiere keystrokes reales (el error del commit 6fdae84 fue cambiar ambos).
    3. La verificación post-fill (keystone) detecta mismatch y lanza
       FieldFillError — recoverable, NO auth — sin exponer jamás el valor.
    4. fetch() propaga FieldFillError sin re-envolverlo (el tipo no se pierde).
    5. El mensaje al usuario nunca culpa a sus credenciales por un fill fallido.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from sky.ingestion.contracts import (
    AllSourcesFailedError,
    AuthenticationError,
    BankCredentials,
    FieldFillError,
    RecoverableIngestionError,
)
from sky.ingestion.sources.bchile_scraper import (
    PASS_SELECTORS,
    RUT_SELECTORS,
    BChileScraperSource,
)

CLAVE_CON_DOLAR = "Abc_123$"


class FakeElement:
    """Input falso que registra si lo llenaron con fill() o type()."""

    def __init__(self, page: FakePage, name: str):
        self._page = page
        self._name = name
        self.calls: list[str] = []

    async def click(self, click_count: int = 1) -> None:
        self.calls.append("click")

    async def fill(self, value: str) -> None:
        self.calls.append("fill")
        self._page.values[self._name] = value

    async def type(self, value: str, delay: int = 0) -> None:
        self.calls.append("type")
        self._page.values[self._name] = value


class FakePage:
    """Page falsa: resuelve el primer selector de cada lista y responde evaluate().

    `rut_display` simula cómo el sitio reformatea el RUT al leerlo de vuelta
    (puntos/guion agregados por Angular, ceros a la izquierda eliminados).
    """

    def __init__(self, *, rut_display: str | None = None):
        self.values: dict[str, str] = {"rut": "", "password": ""}
        self._rut_display = rut_display
        self.rut_el = FakeElement(self, "rut")
        self.pass_el = FakeElement(self, "password")

    async def query_selector(self, sel: str) -> FakeElement | None:
        if sel == RUT_SELECTORS[0]:
            return self.rut_el
        if sel == PASS_SELECTORS[0]:
            return self.pass_el
        return None

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if "maxLength" in script:
            return -1
        if "readOnly" in script:
            return False
        if "el.value" in script:
            # Verificación post-fill: arg = [rut_selector, pass_selector]
            out: list[str | None] = []
            for s in arg:
                if s == RUT_SELECTORS[0]:
                    rut = self._rut_display if self._rut_display is not None else self.values["rut"]
                    out.append(rut)
                else:
                    out.append(self.values["password"])
            return out
        return None


# ── A1: fill() para la clave, type() para el RUT ─────────────────────────────


async def test_fill_password_usa_fill_y_preserva_dolar():
    page = FakePage()
    scraper = BChileScraperSource()

    sel = await scraper._fill_password(page, CLAVE_CON_DOLAR)

    assert sel == PASS_SELECTORS[0]
    assert "fill" in page.pass_el.calls
    assert "type" not in page.pass_el.calls
    assert page.values["password"] == CLAVE_CON_DOLAR


async def test_fill_rut_sigue_usando_type():
    """Regresión anti-6fdae84: el RUT tiene delete-zero-left → keystrokes reales."""
    page = FakePage()
    scraper = BChileScraperSource()

    result = await scraper._fill_rut(page, "22.141.522-1", "221415221")

    assert result is not None
    sel, typed = result
    assert sel == RUT_SELECTORS[0]
    assert "type" in page.rut_el.calls
    assert "fill" not in page.rut_el.calls
    assert typed == "22.141.522-1"  # maxLength -1 → usa el formato con puntos


# ── A2: verificación post-fill (keystone) ────────────────────────────────────


async def test_verify_detecta_password_manglada_sin_exponer_el_valor():
    """Simula el bug de prod: el '$' final no quedó en el input."""
    page = FakePage(rut_display="22.141.522-1")
    page.values["password"] = "Abc_123"  # el '$' se perdió
    scraper = BChileScraperSource()

    with pytest.raises(FieldFillError) as exc_info:
        await scraper._verify_login_fields(
            page, RUT_SELECTORS[0], "221415221", PASS_SELECTORS[0], CLAVE_CON_DOLAR
        )

    err = exc_info.value
    assert err.field == "password"
    assert err.expected_len == 8
    assert err.got_len == 7
    # PII: el mensaje jamás lleva el valor (ni completo ni truncado)
    assert "Abc_123" not in str(err)


async def test_verify_detecta_rut_vacio():
    page = FakePage(rut_display="")
    page.values["password"] = CLAVE_CON_DOLAR
    scraper = BChileScraperSource()

    with pytest.raises(FieldFillError) as exc_info:
        await scraper._verify_login_fields(
            page, RUT_SELECTORS[0], "221415221", PASS_SELECTORS[0], CLAVE_CON_DOLAR
        )

    assert exc_info.value.field == "rut"
    assert "221415221" not in str(exc_info.value)


async def test_verify_acepta_rut_reformateado_por_el_sitio():
    """El sitio agrega puntos/guion al RUT tecleado limpio — no es mismatch."""
    page = FakePage(rut_display="22.141.522-1")
    page.values["password"] = CLAVE_CON_DOLAR
    scraper = BChileScraperSource()

    await scraper._verify_login_fields(
        page, RUT_SELECTORS[0], "221415221", PASS_SELECTORS[0], CLAVE_CON_DOLAR
    )  # no lanza


def test_normalize_rut_tolerante_a_formato_y_ceros():
    norm = BChileScraperSource._normalize_rut_value
    assert norm("22.141.522-1") == norm("221415221")
    # delete-zero-left elimina ceros a la izquierda en el input
    assert norm("022141522-1") == norm("22.141.522-1")
    assert norm("12.345.678-K") == norm("12345678k")


# ── Jerarquía y propagación del error ────────────────────────────────────────


def test_field_fill_error_es_recoverable_no_auth():
    """Recoverable → el router puede failover. NO auth → jamás se presenta
    como 'credenciales rechazadas' ni corta la cadena de providers."""
    assert issubclass(FieldFillError, RecoverableIngestionError)
    assert not issubclass(FieldFillError, AuthenticationError)


async def test_fetch_propaga_field_fill_error_sin_envolver(monkeypatch):
    """fetch() envuelve Exception genéricas en RecoverableIngestionError;
    FieldFillError debe pasar intacto para no perder el tipo."""

    class FakeContext:
        async def new_page(self) -> FakePage:
            return FakePage()

    class FakePool:
        @asynccontextmanager
        async def acquire(self):
            yield FakeContext()

    monkeypatch.setattr(
        "sky.ingestion.sources.bchile_scraper.get_browser_pool", lambda: FakePool()
    )
    scraper = BChileScraperSource()

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise FieldFillError("password", expected_len=8, got_len=7)

    monkeypatch.setattr(scraper, "_login", boom)

    creds = BankCredentials(rut="22141522-1", password=CLAVE_CON_DOLAR)
    with pytest.raises(FieldFillError):
        await scraper.fetch("bchile", creds)


# ── Mensaje al usuario ───────────────────────────────────────────────────────


def test_user_message_field_fill_no_culpa_credenciales():
    from sky.worker.banking_sync import _user_message_for_failure

    exc = AllSourcesFailedError(
        "bchile", [("scraper.bchile", FieldFillError("password", expected_len=8, got_len=7))]
    )
    msg = _user_message_for_failure(exc)

    assert "no es un problema de tu clave" in msg
    assert "RUT o clave incorrectos" not in msg
