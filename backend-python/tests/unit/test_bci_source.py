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


def _scraper(two_fa_timeout_sec: int = 0, grace: float = 0.05) -> BCIScraperSource:
    """Scraper con timings de test: poll rápido, grace y timeout cortos."""
    return BCIScraperSource(
        two_fa_timeout_sec=two_fa_timeout_sec,
        post_submit_grace_sec=grace,
        poll_interval_sec=0.01,
    )


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

    async def fake_post(page, jwt, path, body):
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

    async def fake_post(page, jwt, path, body):
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

    async def fake_post(page, jwt, path, body):
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

    async def fake_post(page, jwt, path, body):
        assert path == BALANCE_PATH
        assert body == {"cuentaNumero": "123"}  # key exacta, sin tipo
        return {"saldoContable": 50000, "saldoDisponible": 48000}

    monkeypatch.setattr(scraper, "_api_post", fake_post)
    assert await scraper._fetch_balance(None, "jwt", "123") == 50000

    async def fake_post_disp(page, jwt, path, body):
        return {"saldoDisponible": 48000}

    monkeypatch.setattr(scraper, "_api_post", fake_post_disp)
    assert await scraper._fetch_balance(None, "jwt", "123") == 48000


def test_scrub_body_redacta_pii_preserva_keys() -> None:
    out = BCIScraperSource._scrub_body('{"rut":"22141522","numero":"00012345678","tipo":"CCT"}')
    assert "22141522" not in out and "00012345678" not in out
    assert '"rut"' in out and '"tipo"' in out and "CCT" in out


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
