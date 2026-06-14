"""
tests/unit/test_bci_source.py — Rework scraper BCI (B-2, 2026-06-13).

Pinea las lecciones de BChile aplicadas a BCI tras la migración del portal
(www.bci.cl, widget embebido) + el contrato del rework:

    1. RUT con type() en #rut_aux; clave con fill() en #clave (preserva '$').
    2. Verificación post-fill: detecta clave manglada Y hidden #rut/#dig sin
       poblar (el JS del form no disparó) → FieldFillError, sin exponer valores.
    3. _post_submit_flow: éxito = dejar el marcador de URL O JWT capturado;
       clave mala SOLO con el mensaje del banco; la ambigüedad jamás es auth.
    4. Normalización: idMovimiento→native_id, monto str→int, tipo→signo,
       fechaMovimiento→date, glosa→raw_description; since filtra.
    5. Bodies CONFIRMADOS (test #1): por-rut {"rut":"<rut>-<dv>"}, saldo
       {"cuentaNumero":"<n>"}, movs {"numeroCuenta":"<n>"} (keys distintas, sin
       tipo). Capture-and-replay queda como fallback de por-rut.
    6. JWT: se captura de CUALQUIER request a apilocal.bci.cl con Bearer (el
       dashboard lo dispara solo, sin navegar al menú).
    7. Rename R-2: BCIScraperSource / scraper.bci registrado en build_all_sources.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest

from sky.ingestion.contracts import (
    PROGRESS_2FA_WAIT_PREFIX,
    AuthenticationError,
    BankCredentials,
    FieldFillError,
    MovementSource,
    RecoverableIngestionError,
    SourceKind,
    SyncFailureKind,
    TwoFactorTimeoutError,
    build_external_id,
    classify_sync_failure,
)
from sky.ingestion.sources.bci_scraper import (
    ACCOUNTS_PATH,
    BALANCE_PATH,
    JWT_HOST,
    LOGIN_ERROR_KEYWORDS,
    LOGIN_URL_MARKER,
    MOVEMENTS_PATH,
    PASS_SELECTORS,
    RUT_HIDDEN_SELECTORS,
    RUT_SELECTORS,
    TWO_FA_KEYWORDS,
    BCIScraperSource,
)

CLAVE_CON_DOLAR = "Abc_123$"
LOGIN_URL = "https://www.bci.cl/corporativo/banco-en-linea/personas"
PERSONAS_URL = "https://www.bci.cl/personas"
TWOFA_BODY = "aprueba el ingreso desde tu app bci digital pass para continuar"


def _scraper(
    two_fa_timeout_sec: int = 0, grace: float = 0.05, jwt_wait: float = 0.04
) -> BCIScraperSource:
    """Scraper con timings de test: poll rápido, grace/timeout/jwt-wait cortos."""
    return BCIScraperSource(
        two_fa_timeout_sec=two_fa_timeout_sec,
        post_submit_grace_sec=grace,
        poll_interval_sec=0.01,
        jwt_wait_sec=jwt_wait,
    )


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anula asyncio.sleep en el módulo para que los nudges/poll no bloqueen."""

    async def _fast(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr("sky.ingestion.sources.bci_scraper.asyncio.sleep", _fast)


# ── Harness de login (fill / verify) ─────────────────────────────────────────


class FakeElement:
    """Input falso que registra si lo llenaron con fill() o type().

    Al teclear el RUT (name='rut'), simula el JS del form de BCI poblando los
    hidden #rut/#dig — salvo que la página tenga hidden_populated=False.
    """

    def __init__(self, page: FakeLoginPage, name: str):
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
        if self._name == "rut" and self._page.hidden_populated:
            clean = re.sub(r"[.\-\s]", "", value).upper()
            self._page.values["hidden_rut"] = clean[:-1]
            self._page.values["hidden_dig"] = clean[-1:] if clean else ""


class FakeLoginPage:
    """Page falsa para fill/verify: resuelve el primer selector de cada lista.

    `rut_display` simula cómo el sitio reformatea el RUT al leerlo de vuelta;
    `hidden_populated=False` simula que el type() no disparó el JS del form.
    """

    def __init__(self, *, rut_display: str | None = None, hidden_populated: bool = True):
        self.values: dict[str, str] = {
            "rut": "", "password": "", "hidden_rut": "", "hidden_dig": "",
        }
        self._rut_display = rut_display
        self.hidden_populated = hidden_populated
        self.rut_el = FakeElement(self, "rut")
        self.pass_el = FakeElement(self, "password")

    def on(self, event: str, handler: Any) -> None:  # fetch() registra el listener
        pass

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
        if "el.value" in script:  # verificación post-fill: arg = [rut, pass, #rut, #dig]
            out: list[str | None] = []
            for s in arg:
                if s == RUT_SELECTORS[0]:
                    val = self._rut_display
                    out.append(self.values["rut"] if val is None else val)
                elif s == PASS_SELECTORS[0]:
                    out.append(self.values["password"])
                elif s == RUT_HIDDEN_SELECTORS[0]:
                    out.append(self.values["hidden_rut"])
                elif s == RUT_HIDDEN_SELECTORS[1]:
                    out.append(self.values["hidden_dig"])
                else:
                    out.append(None)
            return out
        return None


# ── A1: fill() para la clave, type() para el RUT ─────────────────────────────


async def test_fill_password_usa_fill_y_preserva_dolar() -> None:
    page = FakeLoginPage()
    sel = await BCIScraperSource()._fill_password(page, CLAVE_CON_DOLAR)

    assert sel == PASS_SELECTORS[0] == "#clave"
    assert "fill" in page.pass_el.calls
    assert "type" not in page.pass_el.calls
    assert page.values["password"] == CLAVE_CON_DOLAR


async def test_fill_rut_usa_type_en_rut_aux() -> None:
    """El #rut_aux dispara el JS que parte en #rut/#dig → keystrokes reales."""
    page = FakeLoginPage()
    result = await BCIScraperSource()._fill_rut(page, "22.141.522-1", "221415221")

    assert result is not None
    sel, typed = result
    assert sel == RUT_SELECTORS[0] == "#rut_aux"
    assert "type" in page.rut_el.calls
    assert "fill" not in page.rut_el.calls
    assert typed == "22.141.522-1"  # maxLength -1 → usa el formato con puntos


# ── A2: verificación post-fill (keystone) ────────────────────────────────────


async def test_verify_detecta_password_manglada_sin_exponer_el_valor() -> None:
    """El '$' final no quedó en el input — como el bug de prod de BChile."""
    page = FakeLoginPage(rut_display="22.141.522-1")
    page.values["password"] = "Abc_123"
    page.values["hidden_rut"], page.values["hidden_dig"] = "22141522", "1"

    with pytest.raises(FieldFillError) as exc_info:
        await BCIScraperSource()._verify_login_fields(
            page, RUT_SELECTORS[0], "221415221", PASS_SELECTORS[0], CLAVE_CON_DOLAR
        )

    err = exc_info.value
    assert err.field == "password"
    assert err.expected_len == 8 and err.got_len == 7
    assert "Abc_123" not in str(err)  # PII: jamás el valor


async def test_verify_detecta_hidden_rut_no_poblado() -> None:
    """El twist BCI: si el JS del form no pobló #rut/#dig, el banco recibiría un
    RUT vacío. Eso es FieldFillError (técnico), jamás 'clave mala'."""
    page = FakeLoginPage(rut_display="22.141.522-1", hidden_populated=False)
    page.values["password"] = CLAVE_CON_DOLAR  # clave OK

    with pytest.raises(FieldFillError) as exc_info:
        await BCIScraperSource()._verify_login_fields(
            page, RUT_SELECTORS[0], "221415221", PASS_SELECTORS[0], CLAVE_CON_DOLAR
        )

    assert exc_info.value.field == "rut_hidden"


async def test_verify_acepta_login_valido_con_rut_reformateado() -> None:
    """RUT reformateado por el sitio + hidden poblados + clave OK → no lanza."""
    page = FakeLoginPage(rut_display="22.141.522-1")
    page.values["password"] = CLAVE_CON_DOLAR
    page.values["hidden_rut"], page.values["hidden_dig"] = "22141522", "1"

    await BCIScraperSource()._verify_login_fields(
        page, RUT_SELECTORS[0], "221415221", PASS_SELECTORS[0], CLAVE_CON_DOLAR
    )  # no lanza


def test_normalize_rut_tolerante_a_formato_y_ceros() -> None:
    norm = BCIScraperSource._normalize_rut_value
    assert norm("22.141.522-1") == norm("221415221")
    assert norm("022141522-1") == norm("22.141.522-1")
    assert norm("12.345.678-K") == norm("12345678k")


# ── Propagación del FieldFillError por fetch() ───────────────────────────────


async def test_fetch_propaga_field_fill_error_sin_envolver(monkeypatch) -> None:
    """fetch() envuelve Exception genéricas en RecoverableIngestionError;
    FieldFillError debe pasar intacto para no perder el tipo."""

    class FakeContext:
        async def new_page(self) -> FakeLoginPage:
            return FakeLoginPage()

    class FakePool:
        @asynccontextmanager
        async def acquire(self):
            yield FakeContext()

    monkeypatch.setattr(
        "sky.ingestion.sources.bci_scraper.get_browser_pool", lambda: FakePool()
    )
    scraper = BCIScraperSource()

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise FieldFillError("password", expected_len=8, got_len=7)

    monkeypatch.setattr(scraper, "_login", boom)

    creds = BankCredentials(rut="22141522-1", password=CLAVE_CON_DOLAR)
    with pytest.raises(FieldFillError):
        await scraper.fetch("bci", creds)


# ── Harness de post-submit ───────────────────────────────────────────────────


class FakeAuthPage:
    """Página post-submit programable por número de llamadas (determinístico).

    _post_submit_flow hace por tick: chequeo de URL → scan de error (evaluate
    con arg=keywords) → innerText (evaluate sin arg). La página avanza su estado
    contando esas llamadas, sin depender de timing real.
    """

    def __init__(
        self,
        *,
        url: str = LOGIN_URL,
        body_text: str = "ingresa tu rut y clave",
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
                self.url = PERSONAS_URL
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

    async def _fake_capture(self: Any, page: Any, label: str, *, pii_safe: bool = False) -> None:
        labels.append((label, pii_safe))

    monkeypatch.setattr(BCIScraperSource, "_capture_debug", _fake_capture, raising=True)
    return labels


# ── Éxito: dejar el login (URL marker) o JWT capturado ───────────────────────


async def test_url_fuera_del_login_retorna_inmediato(captured) -> None:
    page = FakeAuthPage(url=PERSONAS_URL)
    msgs: list[str] = []

    await _scraper()._post_submit_flow(page, [], msgs.append)

    assert page.body_calls == 0  # salida por URL en el primer tick
    assert msgs == []


async def test_jwt_capturado_es_exito_aunque_siga_en_login_url(captured) -> None:
    """El JWT Bearer a apilocal ⇒ autenticado, aunque la URL no haya cambiado."""
    page = FakeAuthPage(url=LOGIN_URL)

    await _scraper(grace=10.0)._post_submit_flow(page, ["jwt-token"], lambda s: None)

    assert page.body_calls == 0  # _still_on_login corta por el JWT


async def test_url_sale_del_login_tras_unos_ticks(captured) -> None:
    page = FakeAuthPage(flip_url_after=2)
    msgs: list[str] = []

    await _scraper(grace=10.0)._post_submit_flow(page, [], msgs.append)

    assert LOGIN_URL_MARKER not in page.url
    assert not any(m.startswith(PROGRESS_2FA_WAIT_PREFIX) for m in msgs)


# ── Clave mala: SOLO con el mensaje del banco ────────────────────────────────


async def test_error_del_banco_lanza_auth_error(captured) -> None:
    page = FakeAuthPage(login_error="Los datos ingresados no son correctos")

    with pytest.raises(AuthenticationError, match="no son correctos"):
        await _scraper()._post_submit_flow(page, [], lambda s: None)

    assert ("auth_check_login_error", True) in captured


async def test_error_tardio_tambien_es_auth_error(captured) -> None:
    page = FakeAuthPage(error_after=3, error_text="Los datos ingresados no son correctos")

    with pytest.raises(AuthenticationError):
        await _scraper(grace=10.0)._post_submit_flow(page, [], lambda s: None)


def test_keyword_no_son_correctos_pineada() -> None:
    assert "no son correctos" in LOGIN_ERROR_KEYWORDS


# ── 2FA positivo ─────────────────────────────────────────────────────────────


async def test_2fa_positivo_emite_progress_y_termina_al_aprobar(captured) -> None:
    page = FakeAuthPage(body_text=TWOFA_BODY, flip_url_after=4)
    msgs: list[str] = []

    await _scraper(two_fa_timeout_sec=30, grace=10.0)._post_submit_flow(page, [], msgs.append)

    assert any(m.startswith(PROGRESS_2FA_WAIT_PREFIX) for m in msgs)
    assert ("2fa_screen", True) in captured
    assert LOGIN_URL_MARKER not in page.url


async def test_2fa_timeout_es_two_factor_no_auth(captured) -> None:
    page = FakeAuthPage(body_text=TWOFA_BODY)

    with pytest.raises(TwoFactorTimeoutError) as exc_info:
        await _scraper(two_fa_timeout_sec=0, grace=10.0)._post_submit_flow(page, [], lambda s: None)

    assert not isinstance(exc_info.value, AuthenticationError)
    assert ("2fa_timeout", True) in captured
    assert classify_sync_failure(exc_info.value) is SyncFailureKind.NEEDS_2FA


# ── Ambigüedad: jamás se castiga como clave mala ─────────────────────────────


async def test_pantalla_desconocida_sin_form_se_asume_2fa(captured) -> None:
    page = FakeAuthPage(body_text="pantalla nueva del banco sin keywords", password_field=False)
    msgs: list[str] = []

    with pytest.raises(TwoFactorTimeoutError) as exc_info:
        await _scraper(two_fa_timeout_sec=0, grace=0.05)._post_submit_flow(page, [], msgs.append)

    assert not isinstance(exc_info.value, AuthenticationError)
    assert ("2fa_unrecognized_screen", True) in captured
    assert any(m.startswith(PROGRESS_2FA_WAIT_PREFIX) for m in msgs)


async def test_form_pegado_es_recoverable_antibot(captured) -> None:
    """Form de clave visible sin error: el submit no avanzó. Técnico (anti-bot,
    el flag tipo B-1 del DetectCA easysol), no clave mala."""
    page = FakeAuthPage(body_text="ingresa tu rut y clave", password_field=True)

    with pytest.raises(RecoverableIngestionError) as exc_info:
        await _scraper(grace=0.05)._post_submit_flow(page, [], lambda s: None)

    assert not isinstance(exc_info.value, AuthenticationError)
    assert ("post_submit_form_stuck", True) in captured
    assert classify_sync_failure(exc_info.value) is SyncFailureKind.ANTIBOT


def test_match_2fa_no_matchea_el_form_de_login() -> None:
    form_text = (
        "banco en línea. ingresa tu rut y clave de acceso. "
        "descarga la app bci. ¿problemas para ingresar? recupera tu clave."
    )
    assert BCIScraperSource._match_2fa_text(form_text) is False
    assert BCIScraperSource._match_2fa_text(TWOFA_BODY) is True


def test_keywords_2fa_cubren_digital_pass() -> None:
    for kw in ("digital pass", "bci pass"):
        assert kw in TWO_FA_KEYWORDS, f"falta keyword 2FA: {kw}"


# ── Normalización a CanonicalMovement ────────────────────────────────────────


def test_to_canonical_mapea_shape_bci() -> None:
    mov = {
        "fechaMovimiento": "2026-06-10",
        "idMovimiento": "MOV-123",
        "glosa": "COMPRA JUMBO LAS CONDES",
        "monto": "12.345",
        "tipo": "cargo",
    }
    cm = BCIScraperSource()._to_canonical(mov, "bci", None)

    assert cm is not None
    assert cm.amount_clp == -12345  # cargo → gasto (negativo)
    assert cm.raw_description == "COMPRA JUMBO LAS CONDES"
    assert cm.occurred_at == date(2026, 6, 10)
    assert cm.movement_source is MovementSource.ACCOUNT
    assert cm.source_metadata["native_id"] == "MOV-123"
    # idempotencia por native_id (inmune a cambios de glosa/monto)
    assert cm.external_id == build_external_id(
        "bci", date(2026, 6, 10), -12345, "COMPRA JUMBO LAS CONDES",
        MovementSource.ACCOUNT, native_id="MOV-123",
    )


def test_to_canonical_abono_es_positivo_y_fecha_dmy() -> None:
    mov = {
        "fechaMovimiento": "10/06/2026", "idMovimiento": "X",
        "glosa": "SUELDO", "monto": "1500000", "tipo": "abono",
    }
    cm = BCIScraperSource()._to_canonical(mov, "bci", None)

    assert cm is not None
    assert cm.amount_clp == 1_500_000
    assert cm.occurred_at == date(2026, 6, 10)


def test_to_canonical_since_filtra_antiguos() -> None:
    mov = {
        "fechaMovimiento": "2026-01-01", "idMovimiento": "OLD",
        "glosa": "x", "monto": "100", "tipo": "abono",
    }
    assert BCIScraperSource()._to_canonical(mov, "bci", date(2026, 6, 1)) is None


def test_deduplicate_por_external_id() -> None:
    scraper = BCIScraperSource()
    mov = {
        "fechaMovimiento": "2026-06-10", "idMovimiento": "DUP",
        "glosa": "x", "monto": "100", "tipo": "abono",
    }
    a = scraper._to_canonical(mov, "bci", None)
    b = scraper._to_canonical(dict(mov), "bci", None)
    assert a is not None and b is not None
    assert scraper._deduplicate([a, b]) == [a]


def test_parse_int_formato_chileno() -> None:
    p = BCIScraperSource._parse_int
    assert p("12.345") == 12345
    assert p("$1.234.567") == 1_234_567
    assert p("-12.345") == -12345
    assert p("12.345,67") == 12345  # corta en la coma decimal
    assert p(98765) == 98765
    assert p("") == 0
    assert p(None) == 0


# ── Body capture-and-replay ──────────────────────────────────────────────────


def test_accounts_body_rut_con_dv() -> None:
    """Body CONFIRMADO de por-rut (test #1): {"rut": "<rut>-<dv>"}, sin puntos
    y con guion-dv — NO {rut, dig}."""
    scraper = BCIScraperSource()
    assert scraper._accounts_body("22.141.522-1") == {"rut": "22141522-1"}
    assert scraper._accounts_body("221415221") == {"rut": "22141522-1"}  # idempotente
    assert scraper._accounts_body("12.345.678-K") == {"rut": "12345678-K"}


def test_body_for_replica_captura_o_cae_al_fallback() -> None:
    scraper = BCIScraperSource()
    captured = {ACCOUNTS_PATH: '{"rut":"R","dig":"D","extra":"z"}'}
    assert scraper._body_for(captured, ACCOUNTS_PATH, {"fb": 1}) == {
        "rut": "R", "dig": "D", "extra": "z",
    }
    assert scraper._body_for({}, ACCOUNTS_PATH, {"fb": 1}) == {"fb": 1}
    assert scraper._body_for({ACCOUNTS_PATH: "no-json{{"}, ACCOUNTS_PATH, {"fb": 1}) == {"fb": 1}


async def test_list_accounts_usa_body_confirmado(monkeypatch) -> None:
    """Por defecto envía el body CONFIRMADO {"rut":"<rut>-<dv>"}; si trae
    cuentas, no toca el capture-replay."""
    scraper = BCIScraperSource()
    sent: list[dict[str, Any]] = []

    async def fake_post(page, jwt, path, body, headers=None):
        sent.append({"path": path, "body": body})
        return {"cuentas": [{"numero": "123", "tipo": "CCT"}]}

    monkeypatch.setattr(scraper, "_api_post", fake_post)
    captured = {ACCOUNTS_PATH: '{"rut":"R","dig":"D"}'}  # disponible pero NO usado
    accounts = await scraper._list_accounts(None, "jwt", "22.141.522-1", captured)

    assert len(sent) == 1  # un solo POST: el confirmado bastó
    assert sent[0]["path"] == ACCOUNTS_PATH
    assert sent[0]["body"] == {"rut": "22141522-1"}  # CONFIRMADO, no {rut,dig}
    assert accounts == [{"numero": "123", "tipo": "CCT"}]


async def test_list_accounts_fallback_replay_si_confirmado_vacio(monkeypatch) -> None:
    """Si el body confirmado no devuelve cuentas y hay un body capturado del
    frontend, se reintenta con esa forma (capture-and-replay = fallback)."""
    scraper = BCIScraperSource()
    sent: list[dict[str, Any]] = []

    async def fake_post(page, jwt, path, body, headers=None):
        sent.append(body)
        if len(sent) == 1:
            return {"cuentas": []}  # el confirmado no trajo cuentas
        return {"cuentas": [{"numero": "9"}]}  # replay del body capturado

    monkeypatch.setattr(scraper, "_api_post", fake_post)
    captured = {ACCOUNTS_PATH: '{"rut":"22141522","dig":"1"}'}
    accounts = await scraper._list_accounts(None, "jwt", "22.141.522-1", captured)

    assert sent[0] == {"rut": "22141522-1"}  # confirmado primero
    assert sent[1] == {"rut": "22141522", "dig": "1"}  # replay como fallback
    assert accounts == [{"numero": "9"}]


async def test_fetch_movements_usa_numero_cuenta_confirmado(monkeypatch) -> None:
    """Body CONFIRMADO: {"numeroCuenta": "<n>"} — key exacta, sin tipo."""
    scraper = BCIScraperSource()
    sent: dict[str, Any] = {}

    async def fake_post(page, jwt, path, body, headers=None):
        sent["path"], sent["body"] = path, body
        return {"movimientos": [{"idMovimiento": "1"}]}

    monkeypatch.setattr(scraper, "_api_post", fake_post)
    movs = await scraper._fetch_movements(None, "jwt", "12345678")

    assert sent["path"] == MOVEMENTS_PATH
    assert sent["body"] == {"numeroCuenta": "12345678"}
    assert movs == [{"idMovimiento": "1"}]


async def test_fetch_balance_usa_cuenta_numero_con_fallback(monkeypatch) -> None:
    """Body CONFIRMADO: {"cuentaNumero": "<n>"} (key ≠ la de movs, sin tipo);
    saldoContable con fallback a saldoDisponible."""
    scraper = BCIScraperSource()

    async def fake_post(page, jwt, path, body, headers=None):
        assert path == BALANCE_PATH
        assert body == {"cuentaNumero": "123"}  # key exacta, sin tipo
        return {"saldoContable": 50000, "saldoDisponible": 48000}

    monkeypatch.setattr(scraper, "_api_post", fake_post)
    assert await scraper._fetch_balance(None, "jwt", "123") == 50000

    async def fake_post_disp(page, jwt, path, body, headers=None):
        return {"saldoDisponible": 48000}

    monkeypatch.setattr(scraper, "_api_post", fake_post_disp)
    assert await scraper._fetch_balance(None, "jwt", "123") == 48000


def test_scrub_body_redacta_pii_preserva_keys() -> None:
    out = BCIScraperSource._scrub_body('{"rut":"22141522","numero":"00012345678","tipo":"CCT"}')
    assert "22141522" not in out and "00012345678" not in out
    assert '"rut"' in out and '"tipo"' in out and "CCT" in out


# ── _api_post: espeja el request del frontend (fix CORS test #4) ──────────────


class FakeEvalPage:
    """Page falsa que registra el script/arg pasados a evaluate()."""

    def __init__(self, result: Any = None):
        self.script: str | None = None
        self.arg: Any = None
        self._result = result

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        self.script = script
        self.arg = arg
        return self._result


async def test_api_post_omite_credenciales_y_bearer_minuscula() -> None:
    """El fetch in-page espeja el frontend: credentials 'omit' (apilocal auth
    por Bearer, no cookies → evita el bloqueo CORS) + esquema 'bearer' en
    minúscula. Una regresión a 'include'/'Bearer' rompe la llamada."""
    page = FakeEvalPage(result={"cuentas": []})
    out = await BCIScraperSource()._api_post(page, "JWT", ACCOUNTS_PATH, {"rut": "x"})

    assert out == {"cuentas": []}
    assert page.script is not None
    assert 'credentials: "omit"' in page.script
    assert 'credentials: "include"' not in page.script
    assert "`bearer ${jwt}`" in page.script
    assert "`Bearer ${jwt}`" not in page.script
    # url + jwt + body van como args (el jwt nunca se interpola en el script)
    assert page.arg[1] == "JWT" and page.arg[0].endswith(ACCOUNTS_PATH)


async def test_api_post_replica_headers_custom_sin_pisar_los_propios() -> None:
    """Los headers custom capturados del frontend (x-apikey/canal/…) se mergean
    en el fetch — el gateway BFF los exige (400 'Cabeceras incompletas', test
    #5). Pero los nuestros (authorization/content-type/accept) SIEMPRE ganan: se
    asignan DESPUÉS del merge. El apikey va como arg, nunca interpolado."""
    page = FakeEvalPage(result={"cuentas": []})
    extra = {"x-apikey": "SECRET_APIKEY_VALUE", "canal": "WEB"}
    out = await BCIScraperSource()._api_post(page, "JWT", ACCOUNTS_PATH, {"rut": "x"}, extra)

    assert out == {"cuentas": []}
    assert page.script is not None
    # mergea `extra` y recién DESPUÉS fija los nuestros → ganan los propios
    assert "for (const k in extra)" in page.script
    assert page.script.index("for (const k in extra)") < page.script.index(
        'headers["Authorization"]'
    )
    # el apikey va como arg (4º), nunca interpolado en el source del fetch
    assert page.arg[3] == {"x-apikey": "SECRET_APIKEY_VALUE", "canal": "WEB"}
    assert "SECRET_APIKEY_VALUE" not in page.script
    assert "x-apikey" not in page.script


async def test_api_post_sin_headers_capturados_degrada() -> None:
    """Sin headers capturados, _api_post manda {} como extra: degrada al
    comportamiento previo (no rompe)."""
    page = FakeEvalPage(result={"ok": 1})
    out = await BCIScraperSource()._api_post(page, "JWT", ACCOUNTS_PATH, {"rut": "x"})

    assert out == {"ok": 1}
    assert page.arg[3] == {}  # extra_headers None → {}


# ── _scrub_headers: instrumentación PII-safe (§20) ───────────────────────────


def test_scrub_headers_redacta_token_cookie_y_digitos() -> None:
    raw = {
        "authorization": "bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "cookie": "cf_clearance=SECRET; __cf_bm=ALSO-SECRET",
        "content-type": "application/json",
        "accept": "application/json",
        "origin": "https://www.bci.cl",
        "x-cuenta": "00012345678",
    }
    out = BCIScraperSource._scrub_headers(raw)

    # token: queda el esquema (confirma 'bearer' minúscula), nunca el valor
    assert out["authorization"] == "bearer [redacted]"
    # cookie: redactada por completo (cf_clearance/__cf_bm anti-bot)
    assert out["cookie"] == "[redacted]"
    # dígitos largos redactados; headers no sensibles visibles
    assert out["x-cuenta"] == "[digits]"
    assert out["content-type"] == "application/json"
    assert out["accept"] == "application/json"
    assert out["origin"] == "https://www.bci.cl"
    # nada del token ni de la cookie sobrevive en el dict serializado
    flat = str(out)
    assert "eyJhbGci" not in flat and "SECRET" not in flat and "00012345678" not in flat


def test_scrub_headers_authorization_mayuscula_y_sin_esquema() -> None:
    # 'Bearer' mayúscula → esquema preservado
    out = BCIScraperSource._scrub_headers({"Authorization": "Bearer TOK.tok.tok"})
    assert out["Authorization"] == "Bearer [redacted]"
    assert "TOK.tok.tok" not in str(out)
    # authorization sin espacio (token crudo, sin esquema) → todo redactado
    out2 = BCIScraperSource._scrub_headers({"authorization": "eyJraw.tok.value"})
    assert out2["authorization"] == "[redacted]"
    assert "eyJraw" not in str(out2)


def test_scrub_headers_redacta_credencial_por_nombre() -> None:
    """El VALOR de un header con nombre de credencial (x-apikey/token/
    x-ibm-client-id/…) se redacta en el log; application-id/canal quedan
    visibles y la key siempre visible (§20)."""
    out = BCIScraperSource._scrub_headers(
        {
            "x-apikey": "SECRET_APIKEY_VALUE",
            "x-session-token": "abc",
            "x-ibm-client-id": "IBM_CLIENT_SECRET",  # hardening test #6
            "application-id": "fe-bciplus",
            "canal": "WEB",
        }
    )
    assert out["x-apikey"] == "[redacted]"
    assert out["x-session-token"] == "[redacted]"
    assert out["x-ibm-client-id"] == "[redacted]"
    assert out["application-id"] == "fe-bciplus"  # no sensible → valor visible
    assert out["canal"] == "WEB"
    flat = str(out)
    assert "SECRET_APIKEY_VALUE" not in flat and "abc" not in flat
    assert "IBM_CLIENT_SECRET" not in flat


# ── _replayable_headers + _capture_headers: replay de headers (fix test #5/#6) ─


def test_replayable_headers_excluye_pseudo_y_browser_conserva_app() -> None:
    """Excluye los pseudo-headers HTTP/2 (":"-prefixed, que rompían fetch con
    'Invalid name' — test #6), los browser-managed (priority/sec-*/origin/
    user-agent/cookie…) y los que seteamos nosotros (authorization/content-type/
    accept). Conserva los headers de app que el gateway IBM exige. Keys a
    minúscula (X-IBM-Client-Id → x-ibm-client-id)."""
    raw = {
        ":authority": "apilocal.bci.cl",
        ":method": "POST",
        ":path": "/cuentas-busquedas/por-rut",
        ":scheme": "https",
        "host": "apilocal.bci.cl",
        "cookie": "cf_clearance=x",
        "origin": "https://www.bci.cl",
        "referer": "https://www.bci.cl/",
        "user-agent": "UA",
        "accept-encoding": "gzip",
        "priority": "u=1, i",
        "sec-fetch-mode": "cors",
        "sec-ch-ua": '"Chromium"',
        "content-type": "application/json",
        "accept": "application/json",
        "authorization": "bearer TOK",
        "X-IBM-Client-Id": "CLIENT_ID_SECRET",  # mayúscula → se normaliza
        "application-id": "fe-bciplus",
        "channel": "110",
        "reference-service": "saldos",
        "reference-operation": "DatosSucursales",
        "origin-addr": "10.0.0.1",
    }
    out = BCIScraperSource._replayable_headers(raw)
    assert out == {
        "x-ibm-client-id": "CLIENT_ID_SECRET",
        "application-id": "fe-bciplus",
        "channel": "110",
        "reference-service": "saldos",
        "reference-operation": "DatosSucursales",
        "origin-addr": "10.0.0.1",
    }
    # ningún pseudo-header HTTP/2 sobrevive (causaban "Invalid name" en fetch)
    assert not any(k.startswith(":") for k in out)


class FakeRequest:
    """Request falsa: all_headers() async devuelve el set completo (o explota)."""

    def __init__(self, headers: dict[str, str], boom: bool = False):
        self._headers = headers
        self._boom = boom

    async def all_headers(self) -> dict[str, str]:
        if self._boom:
            raise RuntimeError("all_headers falló")
        return self._headers


async def test_capture_headers_guarda_solo_replicables() -> None:
    """Lee all_headers (set completo) y guarda en el store SOLO los replicables;
    cookie/authorization/forbidden nunca entran (los pone el browser o nosotros)."""
    store: dict[str, str] = {}
    req = FakeRequest(
        {
            "authorization": "bearer TOK",
            "cookie": "x=y",
            "origin": "https://www.bci.cl",
            "user-agent": "UA",
            "sec-fetch-mode": "cors",
            "content-type": "application/json",
            "x-apikey": "K",
            "canal": "WEB",
        }
    )
    await BCIScraperSource()._capture_headers([req], store)
    assert store == {"x-apikey": "K", "canal": "WEB"}


async def test_capture_headers_vacio_o_error_no_rompen() -> None:
    """Sin requests, o si all_headers explota, el store queda intacto y no se
    levanta excepción (un fallo de captura jamás rompe el flujo, §20)."""
    store: dict[str, str] = {}
    await BCIScraperSource()._capture_headers([], store)
    assert store == {}
    await BCIScraperSource()._capture_headers([FakeRequest({}, boom=True)], store)
    assert store == {}


# ── Captura del JWT: cualquier path de apilocal.bci.cl (fix test #1) ──────────


def test_jwt_capture_acepta_cualquier_path_de_apilocal() -> None:
    """El dashboard dispara el JWT desde usuarios/<rut>, cashback/<rut> y
    obtenerDatosCliente — no solo el BFF de saldos. Se captura por HOST."""
    f = BCIScraperSource._is_jwt_request
    bearer = {"authorization": "Bearer tok-123"}

    # request NO-BFF del dashboard (auto-disparada) → igual captura
    usuarios_url = f"https://{JWT_HOST}/bci-produccion/api-bci/ms-bciplus-orq/v1.9/usuarios/x"
    assert f(usuarios_url, bearer) == "tok-123"
    # el BFF de saldos también
    assert f(f"https://{JWT_HOST}/.../v3.2/cuentas-busquedas/por-rut", bearer) == "tok-123"


def test_jwt_capture_ignora_otro_host_o_sin_bearer() -> None:
    f = BCIScraperSource._is_jwt_request
    # otro host (aunque tenga Bearer) → no captura
    assert f("https://www.bci.cl/personas", {"authorization": "Bearer x"}) is None
    # apilocal pero sin Bearer → no captura
    assert f(f"https://{JWT_HOST}/x", {"authorization": "Basic abc"}) is None
    assert f(f"https://{JWT_HOST}/x", {}) is None


def test_jwt_capture_case_insensitive_bearer() -> None:
    """El frontend de BCI manda el esquema en MINÚSCULA (`bearer <token>`) —
    confirmado por el censo de red del test #3 (`auth_scheme='bearer'`). La
    captura debe ser case-insensitive: el `startswith("Bearer ")` anterior
    dejaba pasar el token pese a estar en CADA request a apilocal (root cause
    del timeout del JWT)."""
    f = BCIScraperSource._is_jwt_request
    url = f"https://{JWT_HOST}/bci-produccion/api-bci/x"
    # minúscula (lo que BCI manda de verdad), mayúscula y mixta → todas capturan
    assert f(url, {"authorization": "bearer tok.abc.123"}) == "tok.abc.123"
    assert f(url, {"authorization": "Bearer tok.abc.123"}) == "tok.abc.123"
    assert f(url, {"authorization": "BEARER tok.abc.123"}) == "tok.abc.123"
    # esquema bearer sin token → None (no hay nada que capturar)
    assert f(url, {"authorization": "bearer "}) is None
    # otro esquema (case-insensitive) sigue ignorado
    assert f(url, {"authorization": "basic abc"}) is None


# ── Diagnóstico de timeout del JWT: censo + sonda (PII-safe, §20) ─────────────


class FakeReq:
    """Request falsa para _census_entry (url/method/headers)."""

    def __init__(self, url: str, method: str = "GET", auth: str | None = None):
        self.url = url
        self.method = method
        self.headers = {"authorization": auth} if auth is not None else {}


def test_census_entry_pii_safe() -> None:
    e = BCIScraperSource._census_entry(
        FakeReq("https://apilocal.bci.cl/bci-produccion/api-bci/x", "POST", "Bearer T.T.T")
    )
    assert e == {
        "host": "apilocal.bci.cl", "seg": "bci-produccion",
        "method": "POST", "has_auth": True, "auth_scheme": "Bearer",
    }
    # host no-bci.cl (ej. el anti-fraude easysol) → fuera del censo
    assert BCIScraperSource._census_entry(FakeReq("https://detectca.easysol.net/x")) is None
    # sin auth
    e2 = BCIScraperSource._census_entry(FakeReq("https://www.bci.cl/personas"))
    assert e2 is not None
    assert e2["has_auth"] is False and e2["auth_scheme"] is None and e2["seg"] == "personas"


def test_census_entry_redacta_digitos_y_opaca_scheme() -> None:
    # primer segmento con corrida de dígitos → redactado
    e = BCIScraperSource._census_entry(FakeReq("https://www.bci.cl/12345678/x"))
    assert e is not None and e["seg"] == "[digits]"
    # Authorization con token crudo (sin esquema reconocible) → nunca se filtra
    e2 = BCIScraperSource._census_entry(
        FakeReq("https://apilocal.bci.cl/x", "GET", "eyJhbGciOiJIUzI1Ni.abc.def")
    )
    assert e2 is not None and e2["auth_scheme"] == "[opaque]"
    assert "eyJ" not in str(e2)


def test_safe_cookie_summary_solo_nombre_y_dominio() -> None:
    cookies = [
        {"name": "JSESSIONID", "value": "SECRET-VALUE", "domain": ".bci.cl", "expires": 123},
        {"name": "tok12345678", "value": "x", "domain": "apilocal.bci.cl"},
        {"name": "ga", "value": "y", "domain": ".google.com"},  # fuera de bci.cl
    ]
    out = BCIScraperSource._safe_cookie_summary(cookies)

    assert {"name": "JSESSIONID", "domain": ".bci.cl"} in out
    assert {"name": "tok[digits]", "domain": "apilocal.bci.cl"} in out  # key redactada
    assert all("google" not in c["domain"] for c in out)  # filtrado por dominio
    flat = str(out)
    assert "SECRET-VALUE" not in flat and "123" not in flat  # ni valor ni expiry


def test_safe_storage_findings_no_filtra_valores() -> None:
    out = BCIScraperSource._safe_storage_findings(
        "www.bci.cl",
        {"access_token": True, "theme": False, "uid_987654": True},
        {"id_token": True},
    )

    assert {"frame_host": "www.bci.cl", "store": "local", "key": "access_token",
            "looks_like_jwt": True} in out
    assert {"frame_host": "www.bci.cl", "store": "session", "key": "id_token",
            "looks_like_jwt": True} in out
    assert any(f["key"] == "uid_[digits]" for f in out)  # key con dígitos redactada
    assert all("value" not in f for f in out)  # jamás el valor, solo el booleano


def test_safe_url_quita_query_y_redacta() -> None:
    safe = BCIScraperSource._safe_url(
        "https://www.bci.cl/personas/cuenta/12345678?rut=22.141.522-1&t=abc#frag"
    )
    assert "?" not in safe and "#" not in safe
    assert "12345678" not in safe and "22.141.522-1" not in safe
    assert safe.startswith("https://www.bci.cl/personas/cuenta/")


# ── Nudge: itera frames + best-effort ────────────────────────────────────────


class FakeFrame:
    def __init__(
        self, url: str, *, menu_hit: bool = False, raises: bool = False,
        storage: dict | None = None,
    ):
        self.url = url
        self._menu_hit = menu_hit
        self._raises = raises
        self._storage = storage
        self.evaluated = False

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        self.evaluated = True
        if self._raises:
            raise RuntimeError("cross-origin frame")
        if "localStorage" in script:  # STORAGE_PROBE_JS
            return self._storage or {"local": {}, "session": {}}
        return self._menu_hit  # MENU_CLICK_JS


class FakeCtx:
    def __init__(self, cookies: list[Any]):
        self._cookies = cookies

    async def cookies(self) -> list[Any]:
        return self._cookies


class FakeFramesPage:
    def __init__(self, frames: list[FakeFrame], cookies: list[Any] | None = None):
        self.frames = frames
        self.context = FakeCtx(cookies or [])


async def test_navigate_itera_todos_los_frames(no_sleep) -> None:
    """El view de cuentas puede ser un iframe: el nudge prueba todos los frames
    (y traga la excepción del cross-origin) hasta el primer click."""
    f1 = FakeFrame("https://www.bci.cl/personas", raises=True)       # cross-origin → swallow
    f2 = FakeFrame("https://www.bci.cl/personas/x", menu_hit=False)  # sin match
    f3 = FakeFrame("https://apilocal.bci.cl/iframe", menu_hit=True)  # acá clickea
    page = FakeFramesPage([f1, f2, f3])

    await BCIScraperSource()._navigate_to_accounts_menu(page)

    assert f1.evaluated and f2.evaluated and f3.evaluated  # iteró hasta el hit


async def test_navigate_sin_menu_no_revienta(no_sleep) -> None:
    page = FakeFramesPage([FakeFrame("https://www.bci.cl/x", menu_hit=False)])
    await BCIScraperSource()._navigate_to_accounts_menu(page)  # no lanza


# ── _await_jwt: éxito, timeout-diagnóstico y re-nudge ─────────────────────────


async def test_await_jwt_retorna_token_apenas_aparece(no_sleep) -> None:
    token = await _scraper(jwt_wait=0.1)._await_jwt(object(), ["TOK"], {})
    assert token == "TOK"


async def test_await_jwt_timeout_emite_diagnostico_y_renudge(no_sleep, monkeypatch) -> None:
    """Sin JWT: re-nudge UNA vez (mitad de la espera) y diagnóstico de máxima
    información antes de raise — el test #2 no dejó captura por esto."""
    scraper = _scraper(jwt_wait=0.04)  # poll 0.01 → ~4 iters, mitad en 2
    nudges: list[int] = []
    diag: list[dict] = []

    async def fake_nudge(self, page) -> None:
        nudges.append(1)

    async def fake_diag(self, page, census) -> None:
        diag.append(census)

    monkeypatch.setattr(BCIScraperSource, "_navigate_to_accounts_menu", fake_nudge)
    monkeypatch.setattr(BCIScraperSource, "_emit_jwt_timeout_diagnostics", fake_diag)

    with pytest.raises(RecoverableIngestionError):
        await scraper._await_jwt(object(), [], {"sig": {"host": "x"}})

    assert len(nudges) == 1  # re-nudge una sola vez
    assert diag and diag[0] == {"sig": {"host": "x"}}  # diagnóstico con el censo


async def test_probe_tokens_wiring_corre_sonda_por_frame(no_sleep) -> None:
    """Smoke del wiring: corre el JS de storage por frame + cookies, sin lanzar.
    La garantía PII-safe fuerte vive en los helpers puros de arriba
    (_safe_storage_findings / _safe_cookie_summary)."""
    frame = FakeFrame(
        "https://www.bci.cl/personas",
        storage={"local": {"access_token": True}, "session": {}},
    )
    cookies = [{"name": "SID", "value": "SECRET", "domain": ".bci.cl"}]
    page = FakeFramesPage([frame], cookies=cookies)

    await BCIScraperSource()._probe_tokens(page)

    assert frame.evaluated  # corrió la sonda en el frame


# ── R-2: rename + registro ───────────────────────────────────────────────────


def test_source_identifier_kind_y_bancos() -> None:
    s = BCIScraperSource()
    assert s.source_identifier == "scraper.bci"
    assert s.supported_banks == ["bci"]
    assert s.source_kind is SourceKind.SCRAPER


def test_build_all_sources_registra_bci_scraper() -> None:
    from sky.ingestion.sources import build_all_sources

    sources = build_all_sources(include_browser_sources=True)
    assert "scraper.bci" in sources
    assert type(sources["scraper.bci"]).__name__ == "BCIScraperSource"
