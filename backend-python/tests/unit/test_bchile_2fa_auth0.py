"""
tests/unit/test_bchile_2fa_auth0.py — Robustez 2FA post-Auth0 (sprint testers 2026-06-12).

El riesgo que cubre este archivo: un tester con Banco de Chile Pass dispara el
challenge "aprueba en tu app" en el form Auth0 nuevo. Si la pantalla no se
detecta, el flujo viejo expiraba el poll de URL a los 20s y lanzaba
AuthenticationError → needs_reconnection (hard-stop B2) con "tu clave cambió o
el banco la rechazó" — FALSO, con la clave buena. Estos tests pinean:

    1. Éxito = la URL sale del dominio Auth0 (señal positiva).
    2. Clave mala se declara SOLO con el mensaje del banco en pantalla
       (keyword "no son correctos" pineada), en cualquier tick del poll.
    3. 2FA detectado POSITIVAMENTE → progreso visible (prefijo que el worker
       traduce a waiting_2fa) y espera con el timeout 2FA completo.
    4. Pantalla desconocida SIN form de login → se asume 2FA (beneficio de la
       duda + captura debug para refinar keywords). Jamás AuthenticationError.
    5. Form pegado (sigue visible sin error) → RecoverableIngestionError,
       clasificado ANTIBOT. Jamás AuthenticationError.
    6. Timeout/rechazo del 2FA → TwoFactorTimeoutError (recoverable, NO auth).
    7. Capturas pii_safe: solo HTML scrubeado (sin screenshot), RUT/values
       redactados (doctrina §20).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sky.core.config import settings
from sky.ingestion.contracts import (
    PROGRESS_2FA_WAIT_PREFIX,
    AuthenticationError,
    RecoverableIngestionError,
    SyncFailureKind,
    TwoFactorTimeoutError,
    classify_sync_failure,
)
from sky.ingestion.sources.bchile_scraper import (
    LOGIN_DOMAIN,
    LOGIN_ERROR_KEYWORDS,
    TWO_FA_KEYWORDS,
    TWO_FA_KEYWORDS_AUTH0,
    TWO_FA_KEYWORDS_CLASSIC,
    BChileScraperSource,
)

PORTAL_URL = "https://portalpersonas.bancochile.cl/persona/#/inicio"
TWOFA_BODY = "aprueba el ingreso desde tu app banco de chile pass para continuar"


def _scraper(two_fa_timeout_sec: int = 0, grace: float = 0.05) -> BChileScraperSource:
    """Scraper con timings de test: poll rápido, grace y timeout cortos."""
    return BChileScraperSource(
        two_fa_timeout_sec=two_fa_timeout_sec,
        post_submit_grace_sec=grace,
        poll_interval_sec=0.01,
    )


class FakeAuthPage:
    """Página post-submit programable por número de llamadas (determinístico).

    El loop de _post_submit_flow hace por tick: chequeo de URL → scan de error
    (evaluate con arg=keywords) → innerText (evaluate sin arg). La página
    avanza su estado contando esas llamadas — sin depender de timing real.
    """

    def __init__(
        self,
        *,
        url: str = f"https://{LOGIN_DOMAIN}/login?state=abc",
        body_text: str = "ingresa tu rut y clave de acceso",
        password_field: bool = False,
        login_error: str | None = None,
        error_after: int | None = None,
        error_text: str = "",
        flip_url_after: int | None = None,
        body_timeline: list[tuple[int, str]] | None = None,
    ):
        self.url = url
        self.body_text = body_text
        self.password_field = password_field
        self.login_error = login_error
        self.error_after = error_after
        self.error_text = error_text
        self.flip_url_after = flip_url_after
        self.body_timeline = body_timeline or []
        self.error_calls = 0
        self.body_calls = 0

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if isinstance(arg, list):  # scan de _check_login_error(keywords)
            self.error_calls += 1
            if self.login_error is not None:
                return self.login_error
            if self.error_after is not None and self.error_calls >= self.error_after:
                return self.error_text
            return None
        if "innerText" in script:
            self.body_calls += 1
            if self.flip_url_after is not None and self.body_calls >= self.flip_url_after:
                self.url = PORTAL_URL
            for threshold, text in self.body_timeline:
                if self.body_calls >= threshold:
                    self.body_text = text
            return self.body_text
        return None

    async def query_selector(self, sel: str) -> Any:
        return object() if self.password_field else None


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """Registra las llamadas a _capture_debug del scraper bajo test."""
    labels: list[tuple[str, bool]] = []

    async def _fake_capture(
        self: Any, page: Any, label: str, *, pii_safe: bool = False
    ) -> None:
        labels.append((label, pii_safe))

    monkeypatch.setattr(BChileScraperSource, "_capture_debug", _fake_capture, raising=True)
    return labels


# ── Éxito: la URL sale del dominio Auth0 ─────────────────────────────────────


async def test_url_ya_fuera_del_dominio_retorna_inmediato(captured) -> None:
    page = FakeAuthPage(url=PORTAL_URL)
    msgs: list[str] = []

    await _scraper()._post_submit_flow(page, msgs.append)

    assert page.body_calls == 0  # ni un solo scan: salida por URL en el primer tick
    assert msgs == []


async def test_url_sale_del_dominio_tras_unos_ticks(captured) -> None:
    page = FakeAuthPage(flip_url_after=2)
    msgs: list[str] = []

    await _scraper(grace=10.0)._post_submit_flow(page, msgs.append)

    assert page.url == PORTAL_URL
    assert not any(m.startswith(PROGRESS_2FA_WAIT_PREFIX) for m in msgs)


# ── Clave mala: SOLO con el mensaje del banco en pantalla ────────────────────


async def test_error_del_banco_lanza_auth_error(captured) -> None:
    page = FakeAuthPage(login_error="Los datos ingresados no son correctos")

    with pytest.raises(AuthenticationError, match="no son correctos"):
        await _scraper()._post_submit_flow(page, lambda s: None)

    assert ("auth_check_login_error", True) in captured


async def test_error_tardio_tambien_es_auth_error(captured) -> None:
    """El mensaje del banco puede renderearse tarde — el poll lo caza igual."""
    page = FakeAuthPage(error_after=3, error_text="Los datos ingresados no son correctos")

    with pytest.raises(AuthenticationError):
        await _scraper(grace=10.0)._post_submit_flow(page, lambda s: None)


def test_keyword_no_son_correctos_pineada() -> None:
    """Mensaje real del portal Auth0 ("Los datos ingresados no son correctos").
    Si esta keyword sale de la lista, la clave mala deja de detectarse y el
    ciclo needs_reconnection (B1) queda ciego."""
    assert "no son correctos" in LOGIN_ERROR_KEYWORDS


# ── 2FA positivo ─────────────────────────────────────────────────────────────


async def test_2fa_positivo_emite_progress_y_termina_al_aprobar(captured) -> None:
    page = FakeAuthPage(body_text=TWOFA_BODY, flip_url_after=4)
    msgs: list[str] = []

    await _scraper(two_fa_timeout_sec=30, grace=10.0)._post_submit_flow(page, msgs.append)

    assert any(m.startswith(PROGRESS_2FA_WAIT_PREFIX) for m in msgs)
    assert ("2fa_screen", True) in captured
    assert page.url == PORTAL_URL


async def test_2fa_timeout_es_two_factor_no_auth(captured) -> None:
    page = FakeAuthPage(body_text=TWOFA_BODY)

    with pytest.raises(TwoFactorTimeoutError) as exc_info:
        await _scraper(two_fa_timeout_sec=0, grace=10.0)._post_submit_flow(page, lambda s: None)

    assert not isinstance(exc_info.value, AuthenticationError)
    assert ("2fa_timeout", True) in captured
    assert classify_sync_failure(exc_info.value) is SyncFailureKind.NEEDS_2FA


async def test_rechazo_en_app_es_two_factor_no_auth(captured) -> None:
    page = FakeAuthPage(
        body_timeline=[(1, TWOFA_BODY), (3, "la solicitud fue rechazada desde tu app")],
    )

    with pytest.raises(TwoFactorTimeoutError, match="rechazada"):
        await _scraper(two_fa_timeout_sec=30, grace=10.0)._post_submit_flow(page, lambda s: None)


# ── Ambigüedad: jamás se castiga como clave mala ─────────────────────────────


async def test_pantalla_desconocida_sin_form_se_asume_2fa(captured) -> None:
    """Challenge 2FA con texto que no conocemos: el form desapareció pero la
    URL sigue en Auth0. Beneficio de la duda (espera 2FA + progress visible)
    y captura debug para refinar TWO_FA_KEYWORDS con el DOM real."""
    page = FakeAuthPage(body_text="pantalla nueva del banco sin keywords", password_field=False)
    msgs: list[str] = []

    with pytest.raises(TwoFactorTimeoutError) as exc_info:
        await _scraper(two_fa_timeout_sec=0, grace=0.05)._post_submit_flow(page, msgs.append)

    assert not isinstance(exc_info.value, AuthenticationError)
    assert ("2fa_unrecognized_screen", True) in captured
    assert any(m.startswith(PROGRESS_2FA_WAIT_PREFIX) for m in msgs)


async def test_form_pegado_es_recoverable_antibot(captured) -> None:
    """El form de clave sigue visible sin error: el submit no avanzó. Eso es
    un problema técnico (challenge anti-bot / form roto), no clave mala."""
    page = FakeAuthPage(body_text="ingresa tu rut y clave", password_field=True)

    with pytest.raises(RecoverableIngestionError) as exc_info:
        await _scraper(grace=0.05)._post_submit_flow(page, lambda s: None)

    assert not isinstance(exc_info.value, AuthenticationError)
    assert ("post_submit_form_stuck", True) in captured
    assert classify_sync_failure(exc_info.value) is SyncFailureKind.ANTIBOT


# ── Keywords 2FA ─────────────────────────────────────────────────────────────


def test_keywords_2fa_cubren_ambos_portales() -> None:
    """Pin de la cobertura mínima: portal clásico + challenge Auth0."""
    for kw in ("clave dinámica", "digital pass", "bchile pass"):
        assert kw in TWO_FA_KEYWORDS_CLASSIC, f"falta keyword clásica: {kw}"
    for kw in (
        "banco de chile pass",
        "aprueba el ingreso",
        "aprueba en tu app",
        "te enviamos una notificación",
    ):
        assert kw in TWO_FA_KEYWORDS_AUTH0, f"falta keyword Auth0: {kw}"
    # La lista combinada (la que evalúa _post_submit_flow) cubre ambas.
    assert set(TWO_FA_KEYWORDS) == set(TWO_FA_KEYWORDS_CLASSIC) | set(TWO_FA_KEYWORDS_AUTH0)


def test_camino_legacy_post_login_usa_solo_keywords_clasicas() -> None:
    """El check 2FA post-login (portalpersonas) NO debe matchear las frases
    Auth0: el dashboard puede mencionar notificaciones/app en marketing y un
    falso positivo ahí colgaría el sync verificado en prod."""
    dashboard_text = (
        "bienvenido a tu banco. activa la notificación push para enterarte. "
        "te enviamos una notificación con tu cartola mensual. revisa tu app."
    )
    assert BChileScraperSource._match_2fa_text(dashboard_text, TWO_FA_KEYWORDS_CLASSIC) is False


def test_match_2fa_no_matchea_el_form_de_login() -> None:
    """Las keywords son frases compuestas: el texto normal del form de login
    (que menciona 'app' en marketing) no debe disparar el modo 2FA."""
    form_text = (
        "banco en línea. ingresa tu rut y clave de acceso. "
        "descarga la app mi banco. ¿problemas para ingresar? recupera tu clave."
    )
    assert BChileScraperSource._match_2fa_text(form_text) is False
    assert BChileScraperSource._match_2fa_text(TWOFA_BODY) is True


def test_progress_prefix_compatible_con_frontend() -> None:
    """El frontend (BankConnect.jsx) matchea /Esperando aprobaci[oó]n/i sobre
    last_sync_error como fallback de waiting_2fa. No cambiar sin tocar ambos."""
    assert PROGRESS_2FA_WAIT_PREFIX == "⏳ Esperando aprobación 2FA"


# ── Capturas pii_safe ────────────────────────────────────────────────────────


def test_scrub_pii_redacta_values_ruts_y_digitos() -> None:
    html = (
        '<input id="rut" value="22.141.522-1"><input type="password" value=\'secreta$\'>'
        "<p>Hola, tu RUT 22.141.522-1 (o 221415221) tiene un aviso al 987654321.</p>"
    )
    out = BChileScraperSource._scrub_pii(html)

    assert "22.141.522-1" not in out
    assert "221415221" not in out
    assert "987654321" not in out
    assert "secreta$" not in out
    assert 'value="[redacted]"' in out
    assert "[rut]" in out


async def test_capture_pii_safe_solo_html_scrubeado(tmp_path: Path, monkeypatch) -> None:
    """pii_safe=True: sin screenshot (no se puede sanitizar) y HTML scrubeado."""
    monkeypatch.setattr(settings, "scraper_debug_capture", True)
    monkeypatch.setattr(settings, "scraper_debug_dir", str(tmp_path))
    monkeypatch.setattr(settings, "scraper_debug_bucket", "")

    class FakeCapturePage:
        async def screenshot(self, path: str) -> None:
            raise AssertionError("pii_safe no debe tomar screenshot")

        async def content(self) -> str:
            return '<html><input value="22.141.522-1">Texto sin datos</html>'

    await BChileScraperSource()._capture_debug(FakeCapturePage(), "2fa_screen", pii_safe=True)

    assert not list(tmp_path.glob("*.png"))
    htmls = list(tmp_path.glob("bchile_2fa_screen_*.html"))
    assert len(htmls) == 1
    body = htmls[0].read_text(encoding="utf-8")
    assert "22.141.522-1" not in body
    assert 'value="[redacted]"' in body


async def test_capture_normal_mantiene_screenshot(tmp_path: Path, monkeypatch) -> None:
    """pii_safe=False (estados pre-fill): screenshot + HTML crudos, como siempre."""
    monkeypatch.setattr(settings, "scraper_debug_capture", True)
    monkeypatch.setattr(settings, "scraper_debug_dir", str(tmp_path))
    monkeypatch.setattr(settings, "scraper_debug_bucket", "")

    class FakeCapturePage:
        async def screenshot(self, path: str) -> None:
            Path(path).write_bytes(b"fake-png")

        async def content(self) -> str:
            return "<html>form vacío</html>"

    await BChileScraperSource()._capture_debug(FakeCapturePage(), "fill_rut_failed")

    assert list(tmp_path.glob("bchile_fill_rut_failed_*.png"))
    assert list(tmp_path.glob("bchile_fill_rut_failed_*.html"))
